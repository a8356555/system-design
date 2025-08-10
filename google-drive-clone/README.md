# Google Drive Clone

A cloud storage system built with Python/FastAPI that mimics core Google Drive functionality.

## Features

- **File Management**
  - Upload/download files
  - Create folders
  - File versioning
  - Soft delete

- **Sharing & Permissions**
  - Share files with other users
  - Granular permissions (read, write, admin)
  - Shared files listing

- **Storage**
  - S3-compatible storage (MinIO)
  - Storage quota management
  - File deduplication via checksums

- **Authentication**
  - JWT-based authentication
  - User registration/login
  - Secure password hashing

## Architecture

```
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│   FastAPI App   │────│   PostgreSQL    │    │   MinIO/S3      │
│                 │    │   (Metadata)    │    │   (Files)       │
└─────────────────┘    └─────────────────┘    └─────────────────┘
         │
         │
┌─────────────────┐
│     Redis       │
│   (Caching)     │
└─────────────────┘
```

## Quick Start

1. **Clone and setup:**
   ```bash
   git clone <repo>
   cd google-drive-clone
   ```

2. **Run with Docker Compose:**
   ```bash
   docker-compose up -d
   ```

3. **Access the API:**
   - API: http://localhost:8000
   - MinIO Console: http://localhost:9001
   - Docs: http://localhost:8000/docs

## API Endpoints

### Authentication
- `POST /api/auth/register` - Register new user
- `POST /api/auth/token` - Login
- `GET /api/auth/me` - Get current user info

### Files
- `POST /api/files/upload` - Upload file
- `POST /api/files/folder` - Create folder
- `GET /api/files/list` - List files
- `GET /api/files/download/{file_id}` - Download file
- `DELETE /api/files/{file_id}` - Delete file
- `POST /api/files/{file_id}/share` - Share file
- `GET /api/files/shared` - Get shared files

## Environment Variables

- `DATABASE_URL` - PostgreSQL connection string
- `REDIS_URL` - Redis connection string
- `S3_ENDPOINT` - S3/MinIO endpoint
- `S3_ACCESS_KEY` - S3/MinIO access key
- `S3_SECRET_KEY` - S3/MinIO secret key
- `S3_BUCKET_NAME` - Storage bucket name
- `SECRET_KEY` - JWT secret key

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