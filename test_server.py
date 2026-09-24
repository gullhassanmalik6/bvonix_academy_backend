"""Test script to start server and show output."""
import sys
import uvicorn
import multiprocessing

# Fix for Windows multiprocessing issues
if __name__ == "__main__":
    # Set multiprocessing start method for Windows compatibility
    if sys.platform == "win32":
        multiprocessing.freeze_support()
        multiprocessing.set_start_method("spawn", force=True)
    
    print("Starting backend server...")
    print("=" * 50)
    try:
        uvicorn.run(
            "app.main:app",
            host="127.0.0.1",
            port=8000,
            reload=False,  # Disable reload to avoid Windows multiprocessing issues
            log_level="info"
        )
    except Exception as e:
        print(f"ERROR: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
