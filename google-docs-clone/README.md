# Google Docs Clone

A collaborative document editing system built with Python/FastAPI that implements real-time collaboration using Operational Transform.

## Features

- **Real-time Collaboration**
  - Multiple users editing simultaneously
  - Operational Transform for conflict resolution
  - Live cursor tracking
  - User presence indicators

- **Document Management**
  - Create/edit/share documents
  - Granular permissions (read, write, admin)
  - Document history and versioning

- **Collaborative Features**
  - Comments and replies
  - Real-time cursor positions
  - User activity tracking

- **Architecture**
  - WebSocket-based real-time communication
  - Operational Transform algorithm
  - Event-driven updates

## Architecture

```
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│   FastAPI App   │────│   PostgreSQL    │    │   WebSocket     │
│   (REST API)    │    │   (Documents)   │    │   Manager       │
└─────────────────┘    └─────────────────┘    └─────────────────┘
         │                                              │
         │              ┌─────────────────┐             │
         └──────────────│     Redis       │─────────────┘
                        │   (Sessions)    │
                        └─────────────────┘
```

## Operational Transform

The system implements Operational Transform (OT) to handle concurrent edits:

1. **Operations**: Insert, Delete, Retain
2. **Transform Function**: Resolves conflicts between concurrent operations
3. **Server State**: Maintains document state and operation history
4. **Client Sync**: Synchronizes client states with server

## Quick Start

1. **Clone and setup:**
   ```bash
   git clone <repo>
   cd google-docs-clone
   ```

2. **Run with Docker Compose:**
   ```bash
   docker-compose up -d
   ```

3. **Access the API:**
   - API: http://localhost:8000
   - Docs: http://localhost:8000/docs

## API Endpoints

### Documents
- `POST /api/documents/` - Create document
- `GET /api/documents/` - List documents
- `GET /api/documents/{id}` - Get document
- `POST /api/documents/{id}/share` - Share document
- `POST /api/documents/{id}/operations` - Apply operation
- `GET /api/documents/{id}/operations` - Get operations since revision
- `WebSocket /api/documents/{id}/collaborate` - Real-time collaboration

### Comments
- `POST /api/documents/{id}/comments` - Add comment
- `GET /api/documents/{id}/comments` - Get comments

## WebSocket Protocol

### Client -> Server Messages
```json
{
  "type": "operation",
  "operation": {
    "type": "insert",
    "position": 10,
    "content": "Hello"
  },
  "revision": 5
}

{
  "type": "cursor_update",
  "cursor": {
    "position": 15,
    "selection_start": 10,
    "selection_end": 15
  }
}
```

### Server -> Client Messages
```json
{
  "type": "operation",
  "operation": {
    "type": "insert",
    "position": 10,
    "content": "Hello"
  },
  "user_id": 123
}

{
  "type": "cursor_update",
  "cursor": {
    "user_id": 456,
    "username": "john",
    "position": 20
  }
}
```

## Development

1. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

2. **Set up database:**
   ```bash
   alembic upgrade head
   ```

3. **Run development server:**
   ```bash
   uvicorn main:app --reload
   ```

## Testing

```bash
pytest tests/
```

## Operational Transform Example

```python
# Two concurrent operations
op1 = Operation('insert', 5, 'Hello')  # Insert "Hello" at position 5
op2 = Operation('delete', 3, length=2) # Delete 2 chars at position 3

# Transform operations
op1_transformed, op2_transformed = transform_operation(op1, op2)

# op1_transformed: Insert "Hello" at position 3 (adjusted for deletion)
# op2_transformed: Delete 2 chars at position 3 (unchanged)
```