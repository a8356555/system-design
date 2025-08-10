from fastapi import WebSocket, WebSocketDisconnect
from typing import Dict, List, Set, Any
import json
import logging
from sqlalchemy.orm import Session
from app.core.document_service import DocumentService
import asyncio

logger = logging.getLogger(__name__)

class CollaborationManager:
    """Manages WebSocket connections for real-time collaboration"""
    
    def __init__(self):
        # Document ID -> Set of WebSocket connections
        self.document_connections: Dict[int, Set[WebSocket]] = {}
        # WebSocket -> User info
        self.connection_info: Dict[WebSocket, Dict[str, Any]] = {}
        # User ID -> WebSocket connections
        self.user_connections: Dict[int, Set[WebSocket]] = {}
    
    async def connect(self, websocket: WebSocket, document_id: int, user_id: int, username: str):
        """Connect a user to a document collaboration session"""
        await websocket.accept()
        
        # Initialize document connections if needed
        if document_id not in self.document_connections:
            self.document_connections[document_id] = set()
        
        # Add connection
        self.document_connections[document_id].add(websocket)
        self.connection_info[websocket] = {
            'document_id': document_id,
            'user_id': user_id,
            'username': username
        }
        
        # Track user connections
        if user_id not in self.user_connections:
            self.user_connections[user_id] = set()
        self.user_connections[user_id].add(websocket)
        
        # Notify other users that someone joined
        await self.broadcast_to_document(document_id, {
            'type': 'user_joined',
            'user_id': user_id,
            'username': username
        }, exclude=websocket)
        
        logger.info(f"User {username} connected to document {document_id}")
    
    async def disconnect(self, websocket: WebSocket):
        """Disconnect a user from collaboration"""
        if websocket not in self.connection_info:
            return
        
        info = self.connection_info[websocket]
        document_id = info['document_id']
        user_id = info['user_id']
        username = info['username']
        
        # Remove from document connections
        if document_id in self.document_connections:
            self.document_connections[document_id].discard(websocket)
            if not self.document_connections[document_id]:
                del self.document_connections[document_id]
        
        # Remove from user connections
        if user_id in self.user_connections:
            self.user_connections[user_id].discard(websocket)
            if not self.user_connections[user_id]:
                del self.user_connections[user_id]
        
        # Remove connection info
        del self.connection_info[websocket]
        
        # Notify other users that someone left
        await self.broadcast_to_document(document_id, {
            'type': 'user_left',
            'user_id': user_id,
            'username': username
        })
        
        logger.info(f"User {username} disconnected from document {document_id}")
    
    async def broadcast_to_document(self, document_id: int, message: Dict[str, Any], exclude: WebSocket = None):
        """Broadcast a message to all users connected to a document"""
        if document_id not in self.document_connections:
            return
        
        message_json = json.dumps(message)
        connections_to_remove = []
        
        for websocket in self.document_connections[document_id]:
            if websocket == exclude:
                continue
            
            try:
                await websocket.send_text(message_json)
            except Exception as e:
                logger.error(f"Error sending message to WebSocket: {e}")
                connections_to_remove.append(websocket)
        
        # Remove failed connections
        for websocket in connections_to_remove:
            await self.disconnect(websocket)
    
    async def broadcast_operation(self, document_id: int, operation: Dict[str, Any], user_id: int):
        """Broadcast an operation to all users in a document except the sender"""
        message = {
            'type': 'operation',
            'operation': operation,
            'user_id': user_id
        }
        
        # Find sender's websocket to exclude
        sender_websocket = None
        for websocket, info in self.connection_info.items():
            if info['document_id'] == document_id and info['user_id'] == user_id:
                sender_websocket = websocket
                break
        
        await self.broadcast_to_document(document_id, message, exclude=sender_websocket)
    
    async def broadcast_cursor_update(self, document_id: int, cursor_data: Dict[str, Any]):
        """Broadcast cursor position update to all users in a document except the sender"""
        message = {
            'type': 'cursor_update',
            'cursor': cursor_data
        }
        
        # Find sender's websocket to exclude
        sender_websocket = None
        for websocket, info in self.connection_info.items():
            if info['document_id'] == document_id and info['user_id'] == cursor_data['user_id']:
                sender_websocket = websocket
                break
        
        await self.broadcast_to_document(document_id, message, exclude=sender_websocket)
    
    def get_active_users(self, document_id: int) -> List[Dict[str, Any]]:
        """Get list of users currently active in a document"""
        if document_id not in self.document_connections:
            return []
        
        users = []
        seen_users = set()
        
        for websocket in self.document_connections[document_id]:
            if websocket in self.connection_info:
                info = self.connection_info[websocket]
                user_id = info['user_id']
                if user_id not in seen_users:
                    users.append({
                        'user_id': user_id,
                        'username': info['username']
                    })
                    seen_users.add(user_id)
        
        return users

# Global collaboration manager instance
collaboration_manager = CollaborationManager()

async def handle_websocket_message(websocket: WebSocket, message: Dict[str, Any], 
                                 document_service: DocumentService, db: Session):
    """Handle incoming WebSocket messages"""
    message_type = message.get('type')
    
    if websocket not in collaboration_manager.connection_info:
        await websocket.send_text(json.dumps({'error': 'Not connected to any document'}))
        return
    
    info = collaboration_manager.connection_info[websocket]
    document_id = info['document_id']
    user_id = info['user_id']
    
    try:
        if message_type == 'operation':
            # Apply operation using Operational Transform
            operation_data = message['operation']
            client_revision = message.get('revision', 0)
            
            result = document_service.apply_operation(
                document_id, user_id, operation_data, client_revision
            )
            
            # Send confirmation to sender
            await websocket.send_text(json.dumps({
                'type': 'operation_result',
                'success': result['success'],
                'revision': result['revision']
            }))
            
            # Broadcast to other users
            if result['success']:
                await collaboration_manager.broadcast_operation(
                    document_id, result['operation'], user_id
                )
        
        elif message_type == 'cursor_update':
            # Update cursor position
            cursor_data = message['cursor']
            document_service.update_cursor_position(
                document_id, user_id, 
                cursor_data['position'],
                cursor_data.get('selection_start'),
                cursor_data.get('selection_end')
            )
            
            # Broadcast cursor update
            cursor_data['user_id'] = user_id
            cursor_data['username'] = info['username']
            await collaboration_manager.broadcast_cursor_update(document_id, cursor_data)
        
        elif message_type == 'get_active_users':
            # Send list of active users
            active_users = collaboration_manager.get_active_users(document_id)
            await websocket.send_text(json.dumps({
                'type': 'active_users',
                'users': active_users
            }))
        
        elif message_type == 'ping':
            # Respond to ping for connection health
            await websocket.send_text(json.dumps({'type': 'pong'}))
        
        else:
            await websocket.send_text(json.dumps({
                'error': f'Unknown message type: {message_type}'
            }))
    
    except Exception as e:
        logger.error(f"Error handling WebSocket message: {e}")
        await websocket.send_text(json.dumps({
            'error': 'Failed to process message'
        }))