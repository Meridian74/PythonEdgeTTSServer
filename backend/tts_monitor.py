# backend/tts_monitor.py
import subprocess
import os
import datetime
import time
import json
from pathlib import Path


class TTSMonitor:
    def __init__(self):
        self.log_file = "tts_status_history.json"
        self.voices = [
            "hu-HU-NoemiNeural",
            "hu-HU-TamasNeural",
            "hu-HU-SzabolcsNeural",  # próbáljuk meg ezt is
        ]
        self.test_texts = {
            "short": "teszt",
            "hungarian": "Ez egy teszt szöveg magyar nyelven.",
            "english": "This is a test in English."
        }

    def test_voice(self, voice, text_type="short"):
        """Egy hang tesztelése"""
        text = self.test_texts[text_type]
        outfile = f"test_{voice.replace('-', '_')}.mp3"
        timestamp = datetime.datetime.now().isoformat()

        cmd = [
            "edge-tts",
            "--voice", voice,
            "--text", text,
            "--write-media", outfile,
            "--rate", "+0%",
            "--pitch", "+0Hz"
        ]

        result = {
            "voice": voice,
            "timestamp": timestamp,
            "text_type": text_type,
            "text": text,
            "status": "unknown",
            "file_size": 0,
            "error": None,
            "returncode": None
        }

        try:
            # Futtatás timeout-tal
            process = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=30,
                encoding='utf-8',
                errors='ignore'
            )

            result["returncode"] = process.returncode
            result["stdout"] = process.stdout[:500] if process.stdout else ""
            result["stderr"] = process.stderr[:500] if process.stderr else ""

            # Eredmény kiértékelése
            if process.returncode == 0:
                if os.path.exists(outfile):
                    file_size = os.path.getsize(outfile)
                    result["file_size"] = file_size

                    if file_size > 2000:  # Minimum 2KB
                        result["status"] = "OK"
                        print(f"✅ {voice}: OK ({file_size} bytes)")
                    else:
                        result["status"] = "FAIL_SMALL_FILE"
                        result["error"] = f"File too small: {file_size} bytes"
                        print(f"❌ {voice}: Small file ({file_size} bytes)")
                else:
                    result["status"] = "FAIL_NO_FILE"
                    result["error"] = "Output file not created"
                    print(f"❌ {voice}: No output file")
            else:
                result["status"] = "FAIL_RETURNCODE"
                result["error"] = f"Return code: {process.returncode}"
                print(f"❌ {voice}: Return code {process.returncode}")

        except subprocess.TimeoutExpired:
            result["status"] = "FAIL_TIMEOUT"
            result["error"] = "Timeout after 30 seconds"
            print(f"⏰ {voice}: Timeout")
        except Exception as e:
            result["status"] = "FAIL_EXCEPTION"
            result["error"] = str(e)
            print(f"💥 {voice}: Exception - {e}")

        # Fájl takarítás
        if os.path.exists(outfile):
            try:
                os.remove(outfile)
            except:
                pass

        return result

    def run_test(self):
        """Teljes teszt futtatása"""
        print("\n" + "=" * 60)
        print(f"EDGE-TTS TESZT - {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print("=" * 60)

        all_results = []

        for voice in self.voices:
            # Először rövid szöveggel
            result = self.test_voice(voice, "short")
            all_results.append(result)

            # Ha nem sikerült, próbáljuk angolul
            if result["status"] != "OK":
                print(f"  → Próbálom angol szöveggel...")
                result_en = self.test_voice("en-US-JennyNeural", "english")
                all_results.append(result_en)
                break  # Ha angolul sem megy, akkor biztosan API probléma

        # Statisztika
        ok_count = sum(1 for r in all_results if r["status"] == "OK")
        total = len([r for r in all_results if r["voice"].startswith("hu-HU")])

        print(f"\n📊 Összegzés:")
        print(f"   Magyar hangok: {ok_count}/{total} működik")

        # Log mentés
        self.save_results(all_results)

        return all_results

    def save_results(self, results):
        """Eredmények mentése JSON fájlba"""
        try:
            # Korábbi eredmények betöltése
            history = []
            if os.path.exists(self.log_file):
                with open(self.log_file, 'r', encoding='utf-8') as f:
                    history = json.load(f)

            # Új eredmény hozzáadása
            history.extend(results)

            # Csak utolsó 1000 rekord tartása
            if len(history) > 1000:
                history = history[-1000:]

            # Mentés
            with open(self.log_file, 'w', encoding='utf-8') as f:
                json.dump(history, f, indent=2, ensure_ascii=False)

            print(f"📝 Eredmények mentve: {self.log_file}")

        except Exception as e:
            print(f"⚠️ Log mentés hiba: {e}")

    def load_history(self):
        """Előzmények betöltése"""
        if os.path.exists(self.log_file):
            with open(self.log_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        return []

    def generate_report(self):
        """Riport generálás"""
        history = self.load_history()

        if not history:
            print("Nincs elérhető előzmény")
            return

        print("\n" + "=" * 60)
        print("TTS MONITOR RIPORT")
        print("=" * 60)

        # Csoportosítás dátum szerint
        from collections import defaultdict
        daily_stats = defaultdict(lambda: {"total": 0, "ok": 0})

        for record in history:
            if record["voice"].startswith("hu-HU"):
                date = record["timestamp"][:10]  # YYYY-MM-DD
                daily_stats[date]["total"] += 1
                if record["status"] == "OK":
                    daily_stats[date]["ok"] += 1

        # Napi statisztika
        print("\n📅 NAPI STATISZTIKA:")
        for date in sorted(daily_stats.keys(), reverse=True)[:7]:  # Utolsó 7 nap
            stats = daily_stats[date]
            success_rate = (stats["ok"] / stats["total"] * 100) if stats["total"] > 0 else 0
            print(f"  {date}: {stats['ok']}/{stats['total']} ({success_rate:.1f}%)")

        # Utolsó sikeres teszt
        last_success = next((r for r in reversed(history) if r["status"] == "OK"), None)
        if last_success:
            print(f"\n✅ Utolsó sikeres teszt:")
            print(f"   Idő: {last_success['timestamp']}")
            print(f"   Hang: {last_success['voice']}")

        # Aktuális állapot
        hungarian_ok = any(r["status"] == "OK" and r["voice"].startswith("hu-HU")
                           for r in history[-len(self.voices):])

        if hungarian_ok:
            print(f"\n🎉 JELENLEG: MAGYAR HANGOK MŰKÖDNEK")
        else:
            print(f"\n⚠️ JELENLEG: MAGYAR HANGOK NEM MŰKÖDNEK")


def main():
    monitor = TTSMonitor()

    # Parancssori argumentumok
    import sys
    if len(sys.argv) > 1:
        if sys.argv[1] == "report":
            monitor.generate_report()
        elif sys.argv[1] == "test":
            monitor.run_test()
        elif sys.argv[1] == "monitor":
            # Folyamatos monitorozás (pl. óránként)
            import schedule
            print("Folyamatos monitorozás indítása...")

            def job():
                monitor.run_test()
                monitor.generate_report()

            schedule.every().hour.do(job)

            # Azonnali futás
            job()

            while True:
                schedule.run_pending()
                time.sleep(60)
    else:
        # Egyszeri teszt + riport
        monitor.run_test()
        monitor.generate_report()


if __name__ == "__main__":
    main()

