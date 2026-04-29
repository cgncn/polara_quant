"""CalibrationScheduler — runs calibration on a recurring interval."""
import asyncio
import logging
from dataclasses import dataclass

from polara.calibration.engine import CalibrationEngine
from polara.calibration.service import CalibrationService

logger = logging.getLogger(__name__)


@dataclass
class CalibrationScheduler:
    engine: CalibrationEngine
    service: CalibrationService
    interval_hours: int = 24

    async def run(self) -> None:
        while True:
            await self._run_once()
            await asyncio.sleep(self.interval_hours * 3600)

    async def _run_once(self) -> None:
        try:
            results = await self.engine.calibrate_all()
            for result in results:
                await self.service.save(result)
            logger.info("Calibration complete — %d strategies updated", len(results))
        except Exception:
            logger.exception("Calibration run failed")


__all__ = ["CalibrationScheduler"]
