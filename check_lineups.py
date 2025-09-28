import os
import requests
import json
import time
import gspread

# --- CONFIGURAZIONE ---
# Leggiamo i dati dai segreti di GitHub
SORARE_API_KEY = os.environ.get("SORARE_API_KEY")
USER_SLUG = os.environ.get("USER_SLUG")
GSPREAD_CREDENTIALS_JSON = os.environ.get("GSPREAD_CREDENTIALS")
SPREADSHEET_ID = os.environ.get("SPREADSHEET_ID")

# Costanti
API_URL = "https://api.sorare.com/graphql"
FORMAZIONI_SHEET_NAME = "Formazioni Schierate"
HEADERS = ["Competizione", "Nome Formazione", "Giocatore", "Card Slug", "Rarità", "Posizione", "Capitano?"]

# --- QUERY GRAPHQL (tradotte dal tuo script) ---
GET_CURRENT_FIXTURE_QUERY = """
    query GetCurrentFixture {
      so5 {
        so5Fixtures(sport: FOOTBALL, aasmStates: ["started"], first: 1) { 
          nodes { slug, displayName }
        }
      }
    }"""

GET_LEADERBOARDS_QUERY = """
    query GetLeaderboardsFromFixture($slug: String!) {
      so5 {
        so5Fixture(slug: $slug) {
          so5Leaderboards { slug, displayName }
        }
      }
    }"""

GET_USER_LINEUPS_QUERY = """
    query GetUserLineupPublic($slug: String!, $userSlug: String!) {
      so5 {
        so5Leaderboard(slug: $slug) {
          so5LineupsPaginated(first: 10, userSlug: $userSlug) {
            nodes {
              name
              so5Appearances {
                position
                captain
                player { displayName }
                anyCard { slug, rarityTyped }
              }
            }
          }
        }
      }
    }"""

# --- FUNZIONI ---

def sorare_graphql_fetch(query, variables={}):
    """Funzione generica per le chiamate API a Sorare."""
    payload = {"query": query, "variables": variables}
    headers = {
        "APIKEY": SORARE_API_KEY,
        "Content-Type": "application/json",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
    }
    try:
        response = requests.post(API_URL, json=payload, headers=headers, timeout=15)
        response.raise_for_status()
        data = response.json()
        if "errors" in data:
            print(f"ERRORE GraphQL: {data['errors']}")
        return data
    except requests.exceptions.RequestException as e:
        print(f"Errore di rete durante la chiamata API: {e}")
        return None

def main():
    """Funzione principale che esegue tutto il processo."""
    print("--- INIZIO VERIFICA FORMAZIONI SCHIERATE ---")
    start_time = time.time()

    # 1. Autenticazione e preparazione del foglio Google
    if not all([SORARE_API_KEY, USER_SLUG, GSPREAD_CREDENTIALS_JSON, SPREADSHEET_ID]):
        print("ERRORE: Uno o più segreti non sono stati configurati (API_KEY, USER_SLUG, GSPREAD_CREDENTIALS, SPREADSHEET_ID).")
        return

    try:
        print("Autenticazione a Google Sheets...")
        credentials = json.loads(GSPREAD_CREDENTIALS_JSON)
        gc = gspread.service_account_from_dict(credentials)
        spreadsheet = gc.open_by_key(SPREADSHEET_ID)
        
        # Prepara il foglio: crealo se non esiste, puliscilo e scrivi gli header
        try:
            worksheet = spreadsheet.worksheet(FORMAZIONI_SHEET_NAME)
            worksheet.clear()
        except gspread.WorksheetNotFound:
            worksheet = spreadsheet.add_worksheet(title=FORMAZIONI_SHEET_NAME, rows="100", cols="20")
        
        worksheet.update('A1', [HEADERS])
        worksheet.format('A1:G1', {'textFormat': {'bold': True}})
        print(f"Foglio '{FORMAZIONI_SHEET_NAME}' preparato con successo.")
    except Exception as e:
        print(f"ERRORE CRITICO durante l'accesso a Google Sheets: {e}")
        return

    # 2. Trova la Game Week in corso
    print("Cerco la Game Week in corso...")
    fixture_data = sorare_graphql_fetch(GET_CURRENT_FIXTURE_QUERY)
    fixture = fixture_data.get("data", {}).get("so5", {}).get("so5Fixtures", {}).get("nodes", [None])[0]

    if not fixture:
        print("Nessuna Game Week di calcio attiva trovata. Fine.")
        worksheet.update('A2', [["Nessuna formazione trovata (nessuna Game Week attiva)."]])
        return
    print(f"Trovata Game Week: {fixture['displayName']}")

    # 3. Trova le competizioni (leaderboards)
    leaderboards_data = sorare_graphql_fetch(GET_LEADERBOARDS_QUERY, {"slug": fixture['slug']})
    all_leaderboards = leaderboards_data.get("data", {}).get("so5", {}).get("so5Fixture", {}).get("so5Leaderboards", [])
    
    # Filtra le competizioni come nello script originale
    filtered_leaderboards = [
        lb for lb in all_leaderboards 
        if "arena" not in lb['displayName'].lower() and "common" not in lb['displayName'].lower()
    ]
    print(f"Trovate {len(filtered_leaderboards)} competizioni valide da controllare per l'utente '{USER_SLUG}'.")

    # 4. Cerca le formazioni e aggrega i dati
    all_formations_data = []
    for leaderboard in filtered_leaderboards:
        print(f"-> Cerco in: \"{leaderboard['displayName']}\"")
        lineups_data = sorare_graphql_fetch(GET_USER_LINEUPS_QUERY, {"slug": leaderboard['slug'], "userSlug": USER_SLUG})
        lineups = lineups_data.get("data", {}).get("so5", {}).get("so5Leaderboard", {}).get("so5LineupsPaginated", {}).get("nodes", [])
        
        if lineups:
            for lineup in lineups:
                for appearance in lineup.get("so5Appearances", []):
                    row = [
                        leaderboard['displayName'],
                        lineup.get('name', "Senza Nome"),
                        appearance.get("player", {}).get("displayName"),
                        appearance.get("anyCard", {}).get("slug"),
                        appearance.get("anyCard", {}).get("rarityTyped"),
                        appearance.get("position"),
                        "Sì" if appearance.get("captain") else "No"
                    ]
                    all_formations_data.append(row)
        time.sleep(0.5) # Pausa di cortesia

    # 5. Scrivi i risultati sul foglio
    if all_formations_data:
        worksheet.update('A2', all_formations_data)
        print(f"\nSUCCESSO! Trovate e scritte {len(all_formations_data)} carte schierate.")
    else:
        worksheet.update('A2', [[f"Nessuna formazione trovata per l'utente '{USER_SLUG}' nelle competizioni attive."]])
        print(f"\nNessuna formazione trovata per l'utente '{USER_SLUG}'.")
    
    end_time = time.time()
    print(f"--- ESECUZIONE COMPLETATA in {end_time - start_time:.2f} secondi ---")

if __name__ == "__main__":
    main()
