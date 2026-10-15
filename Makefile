.PHONY: up down logs shell migrate migrations superuser test clean smtp-test
up:
	docker compose up --build -d

down:
	docker compose down

logs:
	docker compose logs -f web

shell:
	docker compose exec web python manage.py shell

migrate:
	docker compose exec web python manage.py migrate

migrations:
	docker compose exec web python manage.py makemigrations

superuser:
	docker compose exec web python manage.py createsuperuser

test:
	docker compose exec web python manage.py test

smtp-test:
	docker compose exec web python manage.py test_smtp $(EMAIL)

clean:
	docker compose down -v
