.PHONY: up down migrate revision lint lint-fix test test-unit test-routes generate-key generate-admin-key deploy-check

up:
	docker compose up -d

down:
	docker compose down

migrate:
	docker compose run --rm api alembic upgrade head

revision:
	docker compose run --rm api alembic revision --autogenerate -m "$(msg)"

lint:
	ruff check app/ tests/

lint-fix:
	ruff check --fix app/ tests/

test:
	pytest tests/ -v --tb=short

test-unit:
	pytest tests/test_materiality.py tests/test_prompts.py -v

test-routes:
	pytest tests/test_onboarding.py tests/test_generation.py -v

generate-key:
	@python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"

generate-admin-key:
	@python -c "\
	import hashlib, secrets; \
	k = secrets.token_urlsafe(32); \
	h = hashlib.sha256(k.encode()).hexdigest(); \
	print(f'ADMIN_API_KEY={k}'); \
	print(f'ADMIN_API_KEY_HASH={h}')"

deploy-check:
	curl -s https://$(DOMAIN)/health | python -m json.tool
