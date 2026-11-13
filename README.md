# TechRepair-Hub

Система керування процесами ремонту комп'ютерної техніки (реалізація DDD, патерна Saga та архітектурного оцінювання).

## Налаштування середовища (одноразово)

1. Створіть та активуйте віртуальне середовище Python у корені проєкту:
   ```bash
   python -m venv venv
   .\venv\Scripts\activate
   ```
   *(Якщо Windows блокує активацію, виконайте: `Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser`)*

2. Встановіть необхідні бібліотеки:
   ```bash
   pip install pytest pandas
   ```
---
## Команди для запуску перевірок

* **Лабораторна 2 (Доменне ядро, DDD та інваріанти):**
  ```bash
  python -m pytest tests/
  ```
* **Лабораторна 3 (Оркестрована Saga та компенсації):**
  ```bash
  python -m pytest tests/test_saga.py -v
  ```
* **Лабораторна 4 (Багатометрикове оцінювання архітектури ATAM/CBAM):**
  ```bash
  python scripts/evaluate_architecture.py
  ```
---
## Документація та звіти
* [Звіт до ЛР №1 (Вимоги, архітектурні стилі та C4)](./docs/lab1-report.md)
* [Звіт до ЛР №2 (Доменне ядро та порти)](./docs/lab2-report.md)
* [Звіт до ЛР №3 (Патерн Saga та діаграма послідовності)](./docs/lab3-report.md)
* [Звіт до ЛР №4 (Оцінювання архітектури та ризиків)](./docs/lab4_report.md)
* [ADR 002: Вибір конфігурації інфраструктури](./docs/adr/002-infrastructure-config.md)
