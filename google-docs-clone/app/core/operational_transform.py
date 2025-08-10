from typing import List, Dict, Any, Tuple
from dataclasses import dataclass
import json

@dataclass
class Operation:
    """Represents a single operation in Operational Transform"""
    type: str  # 'insert', 'delete', 'retain'
    position: int
    content: str = None  # For insert operations
    length: int = None   # For delete/retain operations
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'type': self.type,
            'position': self.position,
            'content': self.content,
            'length': self.length
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'Operation':
        return cls(
            type=data['type'],
            position=data['position'],
            content=data.get('content'),
            length=data.get('length')
        )

class OperationalTransform:
    """Implements Operational Transform for collaborative text editing"""
    
    @staticmethod
    def apply_operation(content: str, operation: Operation) -> str:
        """Apply a single operation to content"""
        if operation.type == 'insert':
            return content[:operation.position] + operation.content + content[operation.position:]
        elif operation.type == 'delete':
            return content[:operation.position] + content[operation.position + operation.length:]
        elif operation.type == 'retain':
            return content  # Retain operations don't change content
        else:
            raise ValueError(f"Unknown operation type: {operation.type}")
    
    @staticmethod
    def apply_operations(content: str, operations: List[Operation]) -> str:
        """Apply a sequence of operations to content"""
        for op in operations:
            content = OperationalTransform.apply_operation(content, op)
        return content
    
    @staticmethod
    def transform_operation(op1: Operation, op2: Operation, priority: bool = False) -> Tuple[Operation, Operation]:
        """Transform two concurrent operations against each other"""
        
        # Insert vs Insert
        if op1.type == 'insert' and op2.type == 'insert':
            if op1.position < op2.position:
                return op1, Operation('insert', op2.position + len(op1.content), op2.content)
            elif op1.position > op2.position:
                return Operation('insert', op1.position + len(op2.content), op1.content), op2
            else:  # Same position
                if priority:
                    return op1, Operation('insert', op2.position + len(op1.content), op2.content)
                else:
                    return Operation('insert', op1.position + len(op2.content), op1.content), op2
        
        # Insert vs Delete
        elif op1.type == 'insert' and op2.type == 'delete':
            if op1.position <= op2.position:
                return op1, Operation('delete', op2.position + len(op1.content), length=op2.length)
            else:
                return Operation('insert', max(op1.position - op2.length, op2.position), op1.content), op2
        
        # Delete vs Insert
        elif op1.type == 'delete' and op2.type == 'insert':
            if op2.position <= op1.position:
                return Operation('delete', op1.position + len(op2.content), length=op1.length), op2
            else:
                return op1, Operation('insert', max(op2.position - op1.length, op1.position), op2.content)
        
        # Delete vs Delete
        elif op1.type == 'delete' and op2.type == 'delete':
            if op1.position < op2.position:
                if op1.position + op1.length <= op2.position:
                    # No overlap
                    return op1, Operation('delete', op2.position - op1.length, length=op2.length)
                else:
                    # Overlap
                    overlap = min(op1.position + op1.length, op2.position + op2.length) - op2.position
                    return op1, Operation('delete', op1.position, length=max(0, op2.length - overlap))
            elif op1.position > op2.position:
                if op2.position + op2.length <= op1.position:
                    # No overlap
                    return Operation('delete', op1.position - op2.length, length=op1.length), op2
                else:
                    # Overlap
                    overlap = min(op1.position + op1.length, op2.position + op2.length) - op1.position
                    return Operation('delete', op2.position, length=max(0, op1.length - overlap)), op2
            else:
                # Same position - merge deletions
                max_length = max(op1.length, op2.length)
                return Operation('delete', op1.position, length=max_length), Operation('retain', 0, length=0)
        
        # Retain operations don't affect transformations
        elif op1.type == 'retain':
            return op1, op2
        elif op2.type == 'retain':
            return op1, op2
        
        return op1, op2
    
    @staticmethod
    def transform_operations(ops1: List[Operation], ops2: List[Operation]) -> Tuple[List[Operation], List[Operation]]:
        """Transform two lists of operations against each other"""
        result1, result2 = [], []
        
        for op1 in ops1:
            for op2 in ops2:
                op1_transformed, op2_transformed = OperationalTransform.transform_operation(op1, op2)
                # Update ops for next iterations
                op1 = op1_transformed
            result1.append(op1)
        
        for op2 in ops2:
            for op1 in ops1:
                op1_transformed, op2_transformed = OperationalTransform.transform_operation(op1, op2, priority=True)
                # Update ops for next iterations
                op2 = op2_transformed
            result2.append(op2)
        
        return result1, result2

class DocumentState:
    """Manages document state and operation history"""
    
    def __init__(self, document_id: int, initial_content: str = ""):
        self.document_id = document_id
        self.content = initial_content
        self.revision = 0
        self.operation_history: List[Operation] = []
    
    def apply_operation(self, operation: Operation, user_id: int) -> int:
        """Apply operation and return new revision number"""
        self.content = OperationalTransform.apply_operation(self.content, operation)
        self.operation_history.append(operation)
        self.revision += 1
        return self.revision
    
    def get_operations_since_revision(self, revision: int) -> List[Operation]:
        """Get all operations since a specific revision"""
        if revision >= len(self.operation_history):
            return []
        return self.operation_history[revision:]
    
    def transform_operation_against_history(self, operation: Operation, from_revision: int) -> Operation:
        """Transform an operation against all operations since a revision"""
        operations_since = self.get_operations_since_revision(from_revision)
        
        transformed_op = operation
        for historical_op in operations_since:
            transformed_op, _ = OperationalTransform.transform_operation(transformed_op, historical_op)
        
        return transformed_op