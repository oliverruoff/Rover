import machine
import sys
import uselect
import time

# DAC Pins initialisieren (GPIO 25 ist DAC1, GPIO 26 ist DAC2)
dac1 = machine.DAC(machine.Pin(25))
dac2 = machine.DAC(machine.Pin(26))

def stop_motors():
    # Setzt beide Ausgänge sofort auf 0 Volt
    dac1.write(0)
    dac2.write(0)

# Direkt beim Start zur Sicherheit die Motoren stoppen
stop_motors()

# Poller für den seriellen Input (USB) einrichten
# Damit lesen wir den USB-Port "non-blocking" aus
poller = uselect.poll()
poller.register(sys.stdin, uselect.POLLIN)

# Variablen für die Safety-Funktion
last_input_time = time.ticks_ms()
timeout_ms = 500
motors_active = False

buffer = "" # Sammelt die einkommenden Zeichen

print("ESP32 bereit. Sende Format: wert1,wert2\\n")

while True:
    # 1. PRÜFEN OB DATEN ANKOMMEN (0 = nicht blockieren)
    events = poller.poll(0)
    
    if events:
        # Ein Zeichen lesen
        char = sys.stdin.read(1)
        
        # Wenn ein Zeilenumbruch kommt, ist der Befehl komplett
        if char == '\n' or char == '\r':
            if buffer:
                try:
                    # Befehl am Komma trennen
                    parts = buffer.split(',')
                    if len(parts) == 2:
                        # Werte in Integer umwandeln und strikt auf 0-255 begrenzen
                        val1 = max(0, min(255, int(parts[0])))
                        val2 = max(0, min(255, int(parts[1])))
                        
                        # Neue Werte an die DACs ausgeben
                        dac1.write(val1)
                        dac2.write(val2)
                        
                        # WATCHDOG ZURÜCKSETZEN
                        last_input_time = time.ticks_ms()
                        motors_active = True
                        
                        # Bestätigung für den Pi
                        print(f"ACK:{val1},{val2}")
                except ValueError:
                    pass # Falls Müll gesendet wird, einfach ignorieren
                
                # Buffer für den nächsten Befehl leeren
                buffer = ""
        else:
            # Zeichen zum Buffer hinzufügen
            buffer += char

    # 2. SAFETY CHECK (WATCHDOG)
    # Wenn Motoren aktiv sind, berechne die Zeitdifferenz zum letzten Befehl
    if motors_active and time.ticks_diff(time.ticks_ms(), last_input_time) > timeout_ms:
        stop_motors()
        motors_active = False
        buffer = "" # Alten Datenmüll im Buffer zur Sicherheit verwerfen
        print("SAFETY TIMEOUT: 500ms überschritten. Motoren gestoppt!")
        
    # Kurze Pause (1 Millisekunde), um den Chip nicht mit 100% CPU-Last glühen zu lassen
    time.sleep_ms(1)