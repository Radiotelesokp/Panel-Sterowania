"""
Skrypt uruchamiający serwer API radioteleskopa
"""

import uvicorn
import sys
import os

# Dodaj główny folder do ścieżki
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

def main():
    """Uruchom serwer API"""
    print("Uruchamianie serwera API radioteleskopa...")
    print("API będzie dostępne pod adresem: http://localhost:8000")
    print("Dokumentacja API: http://localhost:8000/docs")
    print("Interfejs webowy: http://localhost:8000/web_interface.html")
    print("\nNaciśnij Ctrl+C aby zatrzymać serwer")

    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_level="info"
    )

if __name__ == "__main__":
    main()
