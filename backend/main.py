# backend/main.py
import os
import logging
import sys
import asyncio
from pathlib import Path
from datetime import datetime
from typing import List, Optional
from fastapi import FastAPI, HTTPException, Query, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
import uvicorn
from pydantic import BaseModel, Field
from tts_service import tts_service

# Windows-specifikus javítás Python 3.13 / edge-tts számára
if sys.platform == 'win32':
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

# Logging beállítás
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


# Pydantic modellek
class TTSRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=4000, description="Felolvasandó szöveg")
    voice: str = Field(default="hu-HU-NoemiNeural", description="Hang azonosító")
    rate: str = Field(default="+0%", description="Sebesség (+0%, +10%, -10%, stb.)")
    pitch: str = Field(default="+0Hz", description="Hangmagasság")
    volume: str = Field(default="+0%", description="Hangerő")
    target_duration_ms: Optional[int] = Field(None, description="Cél időtartam ezredmásodpercben")


class VoiceInfo(BaseModel):
    id: str
    name: str
    displayName: str
    locale: str
    gender: str
    language: str
    neural: bool


class TTSResponse(BaseModel):
    success: bool
    message: str
    file_url: Optional[str] = None
    file_size: Optional[int] = None
    voice: Optional[str] = None
    duration_ms: Optional[int] = None


# FastAPI alkalmazás
app = FastAPI(
    title="Edge-TTS REST API",
    description="Microsoft Edge-TTS REST API szolgáltatás magyar hangokkal",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc"
)

# CORS beállítások
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",  # React frontend
        "http://localhost:5173",  # Vite frontend
        "*"  # Fejlesztéshez, élesben pontosítsd!
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Statikus fájlok (temp audio mappa)
temp_dir = Path("temp_audio")
temp_dir.mkdir(exist_ok=True)
app.mount("/temp_audio", StaticFiles(directory="temp_audio"), name="temp_audio")


# API végpontok
@app.get("/")
async def root():
    """Root endpoint - API információk"""
    return {
        "name": "Edge-TTS REST API",
        "version": "1.0.0",
        "description": "Microsoft Edge-TTS szolgáltatás magyar hangokkal",
        "endpoints": {
            "/voices": "Elérhető hangok listája",
            "/voices/hungarian": "Magyar hangok",
            "/tts": "Szöveg hangfájllá konvertálása (POST)",
            "/health": "API állapot ellenőrzés"
        }
    }


@app.get("/health")
async def health_check():
    """Health check endpoint"""
    try:
        # Ellenőrizzük az Edge-TTS kapcsolatot
        voices = await tts_service.get_available_voices()
        hungarian_count = len([v for v in voices if v['locale'].startswith('hu')])

        return {
            "status": "healthy",
            "timestamp": datetime.now().isoformat(),
            "voices_total": len(voices),
            "hungarian_voices": hungarian_count,
            "services": {
                "edge_tts": "available" if voices else "unavailable"
            }
        }
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        raise HTTPException(status_code=503, detail="Service unavailable")


@app.get("/voices", response_model=List[VoiceInfo])
async def get_all_voices():
    """Összes elérhető hang listája"""
    try:
        voices = await tts_service.get_available_voices()
        return voices
    except Exception as e:
        logger.error(f"Hangok lekérése sikertelen: {e}")
        raise HTTPException(status_code=500, detail="Failed to retrieve voices")


@app.get("/voices/hungarian", response_model=List[VoiceInfo])
async def get_hungarian_voices():
    """Csak magyar hangok listája"""
    try:
        voices = await tts_service.get_hungarian_voices()
        return voices
    except Exception as e:
        logger.error(f"Magyar hangok lekérése sikertelen: {e}")
        raise HTTPException(status_code=500, detail="Failed to retrieve Hungarian voices")


@app.post("/tts", response_model=TTSResponse)
async def text_to_speech(
        request: TTSRequest,
        background_tasks: BackgroundTasks
):
    """
    Szöveg konvertálása hangfájllá

    - **text**: Felolvasandó szöveg (max 4000 karakter)
    - **voice**: Hang azonosító (pl. hu-HU-NoemiNeural)
    - **rate**: Sebesség (+0%, +10%, -10%, stb.)
    - **pitch**: Hangmagasság (+0Hz, +10Hz, -10Hz, stb.)
    - **volume**: Hangerő (+0%, +10%, -10%, stb.)
    - **target_duration_ms**: Kívánt hossza a hangnak (opcionális)
    """
    logger.info(f"TTS kérés: voice={request.voice}, text_length={len(request.text)}")

    try:
        # Hang generálása (itt hívjuk a service-t, ami már kezeli az újragenerálást is)
        success, file_path, duration_ms, error_message = await tts_service.text_to_speech(
            text=request.text,
            voice=request.voice,
            rate=request.rate,
            pitch=request.pitch,
            volume=request.volume,
            target_duration_ms=request.target_duration_ms
        )

        if success and file_path:
            # Fájl URL készítése
            filename = os.path.basename(file_path)
            file_url = f"/temp_audio/{filename}"

            # Fájlméret
            file_size = os.path.getsize(file_path)

            # Háttérben takarítás 5 perc múlva
            background_tasks.add_task(
                delayed_cleanup,
                file_path,
                delay_seconds=300  # 5 perc
            )

            return TTSResponse(
                success=True,
                message="Hangfájl sikeresen generálva",
                file_url=file_url,
                file_size=file_size,
                voice=request.voice,
                duration_ms=duration_ms
            )
        else:
            return TTSResponse(
                success=False,
                message=error_message or "Ismeretlen hiba",
                file_url=None,
                file_size=None,
                voice=request.voice
            )

    except Exception as e:
        logger.error(f"TTS hiba: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Hiba a hanggenerálás során: {str(e)}"
        )


@app.get("/tts/direct")
async def text_to_speech_direct(
        text: str = Query(..., min_length=1, max_length=2000),
        voice: str = Query("hu-HU-NoemiNeural"),
        rate: str = Query("+0%"),
        pitch: str = Query("+0Hz"),
        target_duration_ms: Optional[int] = Query(None),
        background_tasks: BackgroundTasks = None
):
    """
    Direct TTS endpoint - visszaadja a hangfájlt közvetlenül
    """
    try:
        success, file_path, duration_ms, error_message = await tts_service.text_to_speech(
            text=text,
            voice=voice,
            rate=rate,
            pitch=pitch,
            target_duration_ms=target_duration_ms
        )

        if success and file_path:
            # Háttérben takarítás
            if background_tasks:
                background_tasks.add_task(
                    delayed_cleanup,
                    file_path,
                    delay_seconds=300
                )

            return FileResponse(
                path=file_path,
                media_type="audio/mpeg",
                filename=f"tts_{voice}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.mp3"
            )
        else:
            raise HTTPException(
                status_code=500,
                detail=error_message or "Hanggenerálás sikertelen"
            )

    except Exception as e:
        logger.error(f"Direct TTS hiba: {e}")
        raise HTTPException(status_code=500, detail=str(e))


async def delayed_cleanup(file_path: str, delay_seconds: int = 300):
    import asyncio
    await asyncio.sleep(delay_seconds)
    await tts_service.cleanup_file(file_path)


def cleanup_temp_files():
    try:
        temp_dir = Path("temp_audio")
        if temp_dir.exists():
            for file in temp_dir.iterdir():
                if file.is_file():
                    file_age = datetime.now().timestamp() - file.stat().st_mtime
                    if file_age > 3600:
                        file.unlink()
                        logger.info(f"Régi temp fájl törölve: {file.name}")
    except Exception as e:
        logger.warning(f"Temp fájlok takarítása sikertelen: {e}")


@app.on_event("startup")
async def startup_event():
    logger.info("Edge-TTS API indítása...")
    cleanup_temp_files()
    try:
        voices = await tts_service.get_available_voices()
        hungarian = len([v for v in voices if v['locale'].startswith('hu')])
        logger.info(f"API kész. {len(voices)} hang, ebből {hungarian} magyar.")
    except Exception as e:
        logger.error(f"Hangok betöltése sikertelen: {e}")


if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_level="info"
    )
