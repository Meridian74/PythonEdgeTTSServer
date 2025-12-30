# backend/tts_service.py
import edge_tts
import tempfile
import os
import time
from pathlib import Path
import logging
from typing import Dict, List, Optional, Tuple
from mutagen.mp3 import MP3

logger = logging.getLogger(__name__)


class EdgeTTSService:
    """Edge-TTS szolgáltatás kezelő"""

    def __init__(self):
        self.voices_cache = None
        self.cache_time = 0
        self.cache_duration = 3600  # 1 óra cache

    async def get_available_voices(self, force_refresh: bool = False) -> List[Dict]:
        """Elérhető hangok listája"""
        current_time = time.time()

        if not force_refresh and self.voices_cache and (current_time - self.cache_time) < self.cache_duration:
            return self.voices_cache

        try:
            voices = await edge_tts.list_voices()

            categorized = []
            for voice in voices:
                voice_info = {
                    'id': voice.get('ShortName', ''),
                    'name': voice.get('ShortName', ''),
                    'displayName': voice.get('LocalName', voice.get('ShortName', 'Ismeretlen')),
                    'locale': voice.get('Locale', ''),
                    'gender': voice.get('Gender', 'Unknown'),
                    'language': self._extract_language(voice.get('Locale', '')),
                    'neural': 'Neural' in voice.get('ShortName', '') or 'Neural' in voice.get('VoiceType', '')
                }
                categorized.append(voice_info)

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
            logger.error(f"Hiba a hangok lekérésekor: {e}", exc_info=True)
            return [] if self.voices_cache is None else self.voices_cache

    def _extract_language(self, locale: str) -> str:
        """Nyelv kinyerése locale-ból"""
        parts = locale.split('-')
        return parts[0] if len(parts) > 0 else locale

    async def get_hungarian_voices(self) -> List[Dict]:
        """Csak magyar hangok"""
        all_voices = await self.get_available_voices()
        return [v for v in all_voices if v['locale'].startswith('hu')]

    async def _generate_audio(self, text, voice, rate, pitch, volume, output_path) -> bool:
        """Belső segédfüggvény a tényleges Edge-TTS híváshoz"""
        try:
            communicate = edge_tts.Communicate(
                text=text,
                voice=voice,
                rate=rate,
                pitch=pitch,
                volume=volume
            )
            await communicate.save(output_path)
            return os.path.exists(output_path) and os.path.getsize(output_path) > 0
        except Exception as e:
            logger.error(f"Belső generálási hiba: {e}")
            return False

    def _get_mp3_duration_ms(self, file_path) -> int:
        """MP3 fájl hosszának lekérése ms-ben mutagen segítségével"""
        try:
            audio = MP3(file_path)
            return int(audio.info.length * 1000)
        except Exception as e:
            logger.error(f"Hiba a hosszmérésnél: {e}")
            return 0

    async def text_to_speech(
            self,
            text: str,
            voice: str = "hu-HU-NoemiNeural",
            rate: str = "+0%",
            pitch: str = "+0Hz",
            volume: str = "+0%",
            target_duration_ms: Optional[int] = None
    ) -> Tuple[bool, Optional[str], Optional[int], Optional[str]]:
        """
        Szöveg konvertálása hangfájllá méréssel és újragenerálással

        Returns:
            Tuple: (sikeres, fájl_útvonal, időtartam_ms, hiba_üzenet)
        """
        if not text or not text.strip():
            return False, None, 0, "Üres szöveg"

        if len(text) > 4000:
            text = text[:4000] + "..."

        temp_dir = Path("temp_audio")
        temp_dir.mkdir(exist_ok=True)

        # Első generálás az eredeti paraméterekkel
        temp_file = tempfile.NamedTemporaryFile(suffix=".mp3", dir=temp_dir, delete=False)
        temp_path = temp_file.name
        temp_file.close()

        success = await self._generate_audio(text, voice, rate, pitch, volume, temp_path)

        if not success:
            return False, None, 0, "Első generálás sikertelen"

        # Mérés
        actual_duration = self._get_mp3_duration_ms(temp_path)
        logger.info(f"Első generálás kész: {actual_duration}ms (target: {target_duration_ms}ms)")

        # Újragenerálás logikája, ha van célidő és túlléptük
        if target_duration_ms and actual_duration > target_duration_ms:
            # Számoljuk ki, hány százalékos gyorsítás kell (pl. 1.15 -> +15%)
            needed_ratio = actual_duration / target_duration_ms
            extra_rate_percent = int((needed_ratio - 1) * 100)

            # Korlátozás: max +25%
            if extra_rate_percent > 25:
                extra_rate_percent = 25

            if extra_rate_percent > 0:
                new_rate = f"+{extra_rate_percent}%"
                logger.info(f"Túllépés észlelve. Újragenerálás rate={new_rate} beállítással...")

                # Régi fájl törlése, új generálása
                if os.path.exists(temp_path):
                    os.unlink(temp_path)

                success = await self._generate_audio(text, voice, new_rate, pitch, volume, temp_path)
                if success:
                    actual_duration = self._get_mp3_duration_ms(temp_path)
                    logger.info(f"Újragenerálás kész: {actual_duration}ms")
                else:
                    return False, None, 0, "Újragenerálás sikertelen"

        return True, temp_path, actual_duration, None

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

