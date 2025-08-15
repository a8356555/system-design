"""
ClickHouse database client for Lambda Architecture Serving Layer
"""

import asyncio
import logging
from typing import List, Dict, Any, Optional, Union
from clickhouse_driver import Client
from clickhouse_driver.errors import Error as ClickHouseError
import time

logger = logging.getLogger(__name__)


class ClickHouseClient:
    """Async ClickHouse client with connection pooling and retry logic"""
    
    def __init__(self, connection_url: str, max_connections: int = 10, retry_attempts: int = 3):
        self.connection_url = connection_url
        self.max_connections = max_connections
        self.retry_attempts = retry_attempts
        self._connection_pool = []
        self._pool_lock = asyncio.Lock()
        
        # Parse connection URL
        self._parse_connection_url(connection_url)
        
        # Initialize connection pool
        asyncio.create_task(self._initialize_pool())
    
    def _parse_connection_url(self, url: str):
        """Parse ClickHouse connection URL"""
        # Example: clickhouse://user:password@host:port/database
        if url.startswith('clickhouse://'):
            url = url[13:]  # Remove clickhouse://
            
        parts = url.split('@')
        if len(parts) == 2:
            auth_part, host_part = parts
            if ':' in auth_part:
                self.user, self.password = auth_part.split(':', 1)
            else:
                self.user, self.password = auth_part, ''
        else:
            self.user, self.password = 'default', ''
            host_part = url
            
        if '/' in host_part:
            host_port, self.database = host_part.split('/', 1)
        else:
            host_port, self.database = host_part, 'default'
            
        if ':' in host_port:
            self.host, port_str = host_port.split(':', 1)
            self.port = int(port_str)
        else:
            self.host, self.port = host_port, 9000
    
    async def _initialize_pool(self):
        """Initialize connection pool"""
        try:
            for _ in range(self.max_connections):
                client = Client(
                    host=self.host,
                    port=self.port,
                    user=self.user,
                    password=self.password,
                    database=self.database,
                    connect_timeout=10,
                    send_receive_timeout=30
                )
                self._connection_pool.append(client)
            
            logger.info(f"✅ ClickHouse connection pool initialized with {len(self._connection_pool)} connections")
        except Exception as e:
            logger.error(f"❌ Failed to initialize ClickHouse connection pool: {e}")
            raise
    
    async def _get_connection(self) -> Client:
        """Get a connection from the pool"""
        async with self._pool_lock:
            if self._connection_pool:
                return self._connection_pool.pop()
            else:
                # Create new connection if pool is empty
                return Client(
                    host=self.host,
                    port=self.port,
                    user=self.user,
                    password=self.password,
                    database=self.database,
                    connect_timeout=10,
                    send_receive_timeout=30
                )
    
    async def _return_connection(self, client: Client):
        """Return a connection to the pool"""
        async with self._pool_lock:
            if len(self._connection_pool) < self.max_connections:
                self._connection_pool.append(client)
            else:
                # Close excess connections
                try:
                    client.disconnect()
                except:
                    pass
    
    async def execute(self, query: str, params: Optional[Union[tuple, list]] = None) -> int:
        """Execute a query and return number of affected rows"""
        for attempt in range(self.retry_attempts):
            client = None
            try:
                client = await self._get_connection()
                
                start_time = time.time()
                if params:
                    result = await asyncio.get_event_loop().run_in_executor(
                        None, lambda: client.execute(query, params)
                    )
                else:
                    result = await asyncio.get_event_loop().run_in_executor(
                        None, lambda: client.execute(query)
                    )
                
                execution_time = time.time() - start_time
                logger.debug(f"Query executed in {execution_time:.3f}s: {query[:100]}...")
                
                await self._return_connection(client)
                return result if isinstance(result, int) else 0
                
            except ClickHouseError as e:
                logger.error(f"ClickHouse error (attempt {attempt + 1}): {e}")
                if client:
                    try:
                        client.disconnect()
                    except:
                        pass
                
                if attempt == self.retry_attempts - 1:
                    raise
                
                await asyncio.sleep(2 ** attempt)  # Exponential backoff
                
            except Exception as e:
                logger.error(f"Unexpected error executing query (attempt {attempt + 1}): {e}")
                if client:
                    try:
                        client.disconnect()
                    except:
                        pass
                
                if attempt == self.retry_attempts - 1:
                    raise
                
                await asyncio.sleep(2 ** attempt)
    
    async def fetch_one(self, query: str, params: Optional[Union[tuple, list]] = None) -> Optional[Dict[str, Any]]:
        """Fetch one row as a dictionary"""
        for attempt in range(self.retry_attempts):
            client = None
            try:
                client = await self._get_connection()
                
                start_time = time.time()
                if params:
                    result = await asyncio.get_event_loop().run_in_executor(
                        None, lambda: client.execute(query, params, with_column_types=True)
                    )
                else:
                    result = await asyncio.get_event_loop().run_in_executor(
                        None, lambda: client.execute(query, with_column_types=True)
                    )
                
                execution_time = time.time() - start_time
                logger.debug(f"Query executed in {execution_time:.3f}s: {query[:100]}...")
                
                await self._return_connection(client)
                
                if result and len(result) >= 2:
                    data, columns_info = result
                    if data:
                        column_names = [col[0] for col in columns_info]
                        return dict(zip(column_names, data[0]))
                
                return None
                
            except ClickHouseError as e:
                logger.error(f"ClickHouse error (attempt {attempt + 1}): {e}")
                if client:
                    try:
                        client.disconnect()
                    except:
                        pass
                
                if attempt == self.retry_attempts - 1:
                    raise
                
                await asyncio.sleep(2 ** attempt)
                
            except Exception as e:
                logger.error(f"Unexpected error fetching one row (attempt {attempt + 1}): {e}")
                if client:
                    try:
                        client.disconnect()
                    except:
                        pass
                
                if attempt == self.retry_attempts - 1:
                    raise
                
                await asyncio.sleep(2 ** attempt)
    
    async def fetch_all(self, query: str, params: Optional[Union[tuple, list]] = None) -> List[Dict[str, Any]]:
        """Fetch all rows as a list of dictionaries"""
        for attempt in range(self.retry_attempts):
            client = None
            try:
                client = await self._get_connection()
                
                start_time = time.time()
                if params:
                    result = await asyncio.get_event_loop().run_in_executor(
                        None, lambda: client.execute(query, params, with_column_types=True)
                    )
                else:
                    result = await asyncio.get_event_loop().run_in_executor(
                        None, lambda: client.execute(query, with_column_types=True)
                    )
                
                execution_time = time.time() - start_time
                logger.debug(f"Query executed in {execution_time:.3f}s, returned {len(result[0]) if result and result[0] else 0} rows")
                
                await self._return_connection(client)
                
                if result and len(result) >= 2:
                    data, columns_info = result
                    if data:
                        column_names = [col[0] for col in columns_info]
                        return [dict(zip(column_names, row)) for row in data]
                
                return []
                
            except ClickHouseError as e:
                logger.error(f"ClickHouse error (attempt {attempt + 1}): {e}")
                if client:
                    try:
                        client.disconnect()
                    except:
                        pass
                
                if attempt == self.retry_attempts - 1:
                    raise
                
                await asyncio.sleep(2 ** attempt)
                
            except Exception as e:
                logger.error(f"Unexpected error fetching all rows (attempt {attempt + 1}): {e}")
                if client:
                    try:
                        client.disconnect()
                    except:
                        pass
                
                if attempt == self.retry_attempts - 1:
                    raise
                
                await asyncio.sleep(2 ** attempt)
    
    async def ping(self) -> bool:
        """Test connection health"""
        try:
            result = await self.fetch_one("SELECT 1 as ping")
            return result is not None and result.get('ping') == 1
        except Exception as e:
            logger.error(f"ClickHouse ping failed: {e}")
            return False
    
    async def close(self):
        """Close all connections in the pool"""
        async with self._pool_lock:
            for client in self._connection_pool:
                try:
                    client.disconnect()
                except:
                    pass
            self._connection_pool.clear()
            
        logger.info("ClickHouse connection pool closed")
    
    async def get_table_info(self, table_name: str) -> Dict[str, Any]:
        """Get table information"""
        query = """
        SELECT 
            count() as row_count,
            formatReadableSize(sum(bytes)) as size,
            min(modification_time) as oldest_data,
            max(modification_time) as newest_data
        FROM system.parts
        WHERE table = %s AND active = 1
        """
        result = await self.fetch_one(query, (table_name,))
        return result or {}