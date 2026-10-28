# How to run the app

From the root directory (thus is not from the `src` directory) run `uvicorn src.api:app --reload`.

# How to run tests

From the root project directory run `PYTHONPATH=. pytest`.

# Description of the API

- `/api/v1/ask/reaction?substance={name or Wikidata entity ID}&other_entity={name or Wikidata entity ID} — return possible reactions between two specified substances. Try `water` and `glucose` as a example.
- `/api/v1/ask/chemical-properties?substance={name or Wikidata entity ID}` — return chemical properties of the substance.
- `/api/v1/ask/substance-kind?substance={name or Wikidata entity ID}` — returns what is the subtance is in particular, for example is it a mixture or not.
- `/api/v1/ask/physical-properties?substance={name or Wikidata entity ID}` — returns physical properties of the substance.
- `/api/v1/ask/mixture-component?mixture={name or Wikidata entity ID}` — returns components of the mixture. Try `milk` as an example.
