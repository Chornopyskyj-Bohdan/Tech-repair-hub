# TechRepair-Hub

Система керування процесами ремонту комп'ютерної техніки (DDD, Гексагональна архітектура, патерн Saga, оцінювання ATAM/CBAM, REST API та контрактне тестування).

## Інструменти та версії

* **Python:** 3.11+
* **FastAPI:** 0.115+ (REST API адаптер та OpenAPI 3.1)
* **httpx:** 0.27+ (HTTP-клієнт та `TestClient`)
* **pytest:** 8.0+ (модульні, інтеграційні та контрактні тести)
* **pandas:** 2.2+ (скрипт багатометрикового оцінювання архітектури)

## Налаштування середовища (одноразово)

1. Створіть та активуйте віртуальне середовище Python у корені проєкту:
   ```bash
   python -m venv venv
   .\venv\Scripts\activate
   ```
   *(Якщо Windows блокує активацію, виконайте: `Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser`)*

2. Встановіть необхідні бібліотеки:
   ```bash
   pip install pytest pandas fastapi httpx
   ```

---

## Команди для запуску перевірок

* **Лабораторна 2 (Доменне ядро, DDD та інваріанти):**
  ```bash
  python -m pytest tests/test_repair_order.py -v
  ```
* **Лабораторна 3 (Оркестрована Saga та компенсації):**
  ```bash
  python -m pytest tests/test_saga.py -v
  ```
* **Лабораторна 4 (Багатометрикове оцінювання архітектури ATAM/CBAM):**
  ```bash
  python scripts/evaluate_architecture.py
  ```
* **Лабораторна 5 (REST API та контрактні тести Consumer/Provider):**
  ```bash
  python -m pytest tests/test_api.py tests/test_consumer_contract.py tests/test_provider_contract.py -v
  ```
* **Запуск усіх тестів проєкту одночасно:**
  ```bash
  python -m pytest tests/ -v
  ```

---

## Документація, специфікації та звіти

* [Звіт до ЛР №1 (Вимоги, архітектурні стилі та C4)](./docs/lab1-report.md)[cite: 2]
* [Звіт до ЛР №2 (Доменне ядро та порти)](./docs/lab2-report.md)[cite: 2]
* [Звіт до ЛР №3 (Патерн Saga та діаграма послідовності)](./docs/lab3-report.md)[cite: 2]
* [Звіт до ЛР №4 (Оцінювання архітектури та ризиків)](./docs/lab4_report.md)[cite: 2]
* [Звіт до ЛР №5 (REST API та контрактне тестування)](./docs/lab5-report.md)
* [OpenAPI 3.1.1 специфікація](./docs/openapi.yaml)
* [ADR 001: Вибір архітектурного стилю](./docs/adr/001-architectural-style.md)[cite: 2]
* [ADR 002: Вибір конфігурації інфраструктури](./docs/adr/002-infrastructure-config.md)[cite: 2]
* [ADR 003: Вибір стилю API (REST vs gRPC vs GraphQL)](./docs/adr/003-api-style.md)