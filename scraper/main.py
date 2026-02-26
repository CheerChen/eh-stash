import asyncio
import logging
import signal
import sys
from loop import run_loop

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

async def main():
    logger.info("Starting Scraper Service")
    
    # Handle signals
    loop = asyncio.get_running_loop()
    stop = asyncio.Event()
    
    def _handle_signal():
        logger.info("Received exit signal. Stopping...")
        stop.set()
        # We can just let the loop task be cancelled or wait for it
        # But run_loop is an infinite loop.
        # We should probably pass a stop event to run_loop or just cancel it.
    
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, _handle_signal)

    # Run the loop
    # Since run_loop is infinite, we just await it.
    # To stop, we can cancel it.
    task = asyncio.create_task(run_loop())
    
    try:
        await stop.wait()
    except asyncio.CancelledError:
        pass
    finally:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        logger.info("Scraper stopped.")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
