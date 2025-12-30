# backend/tts_service.py
import asyncio
import edge_tts
import tempfile
import os
from pathlib import Path
import logging
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


class EdgeTTSService:
    """Edge-TTS szolgáltatás kezelő"""

    def __init__(self):
        self.voices_cache = None
        self.cache_time = 0
        self.cache_duration = 3600  # 1 óra cache

    async def get_available_voices(self, force_refresh: bool = False) -> List[Dict]:
        """Elérhető hangok listája"""
        current_time = asyncio.get_event_loop().time()

        if not force_refresh and self.voices_cache and (current_time - self.cache_time) < self.cache_duration:
            return self.voices_cache

        try:
            voices = await edge_tts.list_voices()

            # Csoportosítás nyelv szerint
            categorized = []
            for voice in voices:
                voice_info = {
                    'id': voice['ShortName'],
                    'name': voice['ShortName'],
                    'displayName': voice['LocalName'],
                    'locale': voice['Locale'],
                    'gender': voice['Gender'],
                    'language': self._extract_language(voice['Locale']),
                    'neural': 'Neural' in voice['VoiceType']
                }
                categorized.append(voice_info)

            # Rendezés: magyar előre, majd neural hangok
            categorized.sort(key=lambda x: (
                0 if x['locale'].startswith('hu') else 1,
                0 if x['neural'] else 1,
                x['displayName']
            ))

            self.voices_cache = categorized
            self.cache_time = current_time

            logger.info(f"Hangok betöltve: {len(categorized)} hang")
            return categorized

        except Exception as e:
            logger.error(f"Hiba a hangok lekérésekor: {e}")
            raise

    def _extract_language(self, locale: str) -> str:
        """Nyelv kinyerése locale-ból"""
        parts = locale.split('-')
        return parts[0] if len(parts) > 0 else locale

    async def get_hungarian_voices(self) -> List[Dict]:
        """Csak magyar hangok"""
        all_voices = await self.get_available_voices()
        return [v for v in all_voices if v['locale'].startswith('hu')]

    async def text_to_speech(
            self,
            text: str,
            voice: str = "hu-HU-NoemiNeural",
            rate: str = "+0%",
            pitch: str = "+0Hz",
            volume: str = "+0%"
    ) -> Tuple[bool, Optional[str], Optional[str]]:
        """
        Szöveg konvertálása hangfájllá

        Args:
            text: Felolvasandó szöveg
            voice: Hang azonosító
            rate: Sebesség (+0%, +10%, -10%, stb.)
            pitch: Hangmagasság (+0Hz, +10Hz, -10Hz, stb.)
            volume: Hangerő (+0%, +10%, -10%, stb.)

        Returns:
            Tuple: (sikeres, fájl_útvonal, hiba_üzenet)
        """
        if not text or not text.strip():
            return False, None, "Üres szöveg"

        # Szöveg korlátozása (Edge-TTS limit ~4000 karakter)
        if len(text) > 4000:
            text = text[:4000] + "..."

        temp_file = None
        try:
            # Ideiglenes fájl létrehozása
            temp_dir = Path("temp_audio")
            temp_dir.mkdir(exist_ok=True)

            temp_file = tempfile.NamedTemporaryFile(
                suffix=".mp3",
                dir=temp_dir,
                delete=False
            )
            temp_path = temp_file.name
            temp_file.close()

            logger.info(f"Hang generálása: '{text[:50]}...' -> {voice}")

            # Edge-TTS kommunikáció
            communicate = edge_tts.Communicate(
                text=text,
                voice=voice,
                rate=rate,
                pitch=pitch,
                volume=volume
            )

            # Fájl mentése
            await communicate.save(temp_path)

            # Ellenőrzés
            if os.path.exists(temp_path) and os.path.getsize(temp_path) > 1024:
                file_size = os.path.getsize(temp_path)
                logger.info(f"Hangfájl létrehozva: {temp_path} ({file_size} bytes)")
                return True, temp_path, None
            else:
                error_msg = "A generált hangfájl túl kicsi vagy nem létezik"
                logger.error(error_msg)
                return False, None, error_msg

        except asyncio.TimeoutError:
            error_msg = "Időtúllépés a hanggenerálás során"
            logger.error(error_msg)
            return False, None, error_msg
        except Exception as e:
            error_msg = f"Hiba a hanggenerálás során: {str(e)}"
            logger.error(error_msg, exc_info=True)
            return False, None, error_msg
        finally:
            # Temp file descriptor bezárása
            if temp_file and not temp_file.closed:
                temp_file.close()

    async def cleanup_file(self, file_path: str):
        """Fájl törlése"""
        try:
            if os.path.exists(file_path):
                os.unlink(file_path)
                logger.debug(f"Fájl törölve: {file_path}")
        except Exception as e:
            logger.warning(f"Fájl törlése sikertelen: {file_path} - {e}")


# Singleton instance
tts_service = EdgeTTSService()

