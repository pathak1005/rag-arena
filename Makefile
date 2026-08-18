PY := .venv/Scripts/python.exe

.PHONY: install api ui neo4j down test docker clean

install:
	py -3.12 -m venv .venv
	$(PY) -m pip install --upgrade pip
	$(PY) -m pip install -r requirements.txt

api:
	$(PY) -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload

ui:
	$(PY) -m streamlit run ui/streamlit_app.py --server.port 8501

neo4j:
	docker compose up -d neo4j
	@echo "Neo4j Browser: http://localhost:7474  (neo4j / helios-dev-password)"

down:
	docker compose down

test:
	$(PY) -m pytest tests/ -q

docker:
	docker build -t rag-arena:local .
	docker run --rm -p 8000:8000 -p 8501:8501 rag-arena:local

clean:
	rm -rf data/chroma data/briefs/*.md __pycache__ app/__pycache__
