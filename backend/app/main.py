"""Main FastAPI application entry point."""
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import logging
from contextlib import asynccontextmanager

from app.config import settings
from app.core.exceptions import AppException
from app.api.routes import upload, tasks, audiobooks, websocket

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan handler."""
    # Startup
    logger.info("Starting PDF to Audiobook API...")
    settings.ensure_directories()

    yield

    # Shutdown
    logger.info("Shutting down PDF to Audiobook API...")
    # Cleanup old tasks
    from app.services.task_manager import task_manager
    task_manager.cleanup_old_tasks()


# Create FastAPI application
app = FastAPI(
    title="PDF to Audiobook API",
    description="Convert PDF books to audiobooks with AI-powered summarization",
    version="1.0.0",
    lifespan=lifespan
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Exception handlers
@app.exception_handler(AppException)
async def app_exception_handler(request: Request, exc: AppException):
    """Handle custom application exceptions."""
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": exc.message,
            "code": exc.code
        }
    )


@app.exception_handler(Exception)
async def general_exception_handler(request: Request, exc: Exception):
    """Handle unexpected exceptions."""
    logger.error(f"Unexpected error: {exc}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={
            "error": "An unexpected error occurred",
            "code": "INTERNAL_ERROR"
        }
    )


# Include routers
app.include_router(upload.router)
app.include_router(tasks.router)
app.include_router(audiobooks.router)
app.include_router(websocket.router)


# Health check endpoint
@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "healthy", "service": "pdf-to-audiobook-api"}


# Root endpoint
@app.get("/")
async def root():
    """Root endpoint with API information."""
    return {
        "name": "PDF to Audiobook API",
        "version": "1.0.0",
        "docs": "/docs",
        "health": "/health"
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8000,
        reload=True
    )
