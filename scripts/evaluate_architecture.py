import pandas as pd

# 1. Визначення альтернатив та синтетичних показників
data = {
    "Alternative": ["A (Базовий Моноліт)", "B (Модульний + PaaS/Saga)", "C (Мікросервіси K8s)"],
    "Cost_USD": [50, 150, 500],       # Мінімізація (Вартість інфраструктури)
    "Latency_ms": [300, 200, 150],    # Мінімізація (Час обробки в пік)
    "SLA_percent": [99.0, 99.9, 99.99], # Максимізація (Відмовостійкість)
    "Complexity": [3, 6, 9]           # Мінімізація (Складність підтримки, 1-10)
}
df = pd.DataFrame(data)

# 2. Функції нормалізації
def normalize_min(col):
    """Для критеріїв, які потрібно мінімізувати: (value - min) / (max - min)"""
    return (col - col.min()) / (col.max() - col.min())

def normalize_max(col):
    """Для критеріїв, які потрібно максимізувати: (max - value) / (max - min)"""
    return (col.max() - col) / (col.max() - col.min())

# Нормована матриця втрат
df_norm = pd.DataFrame()
df_norm["Alternative"] = df["Alternative"]
df_norm["Cost_Loss"] = normalize_min(df["Cost_USD"])
df_norm["Latency_Loss"] = normalize_min(df["Latency_ms"])
df_norm["SLA_Loss"] = normalize_max(df["SLA_percent"])
df_norm["Complexity_Loss"] = normalize_min(df["Complexity"])

# 3. Визначення ваг для двох сценаріїв
# Набір 1: Пріоритет на економію бюджету та простоту (Стартап)
weights_scenario_1 = {"Cost": 0.5, "Latency": 0.1, "SLA": 0.1, "Complexity": 0.3}

# Набір 2: Пріоритет на надійність та продуктивність (Enterprise масштабування)
weights_scenario_2 = {"Cost": 0.1, "Latency": 0.3, "SLA": 0.5, "Complexity": 0.1}

def calculate_J(row, weights):
    return (row["Cost_Loss"] * weights["Cost"] +
            row["Latency_Loss"] * weights["Latency"] +
            row["SLA_Loss"] * weights["SLA"] +
            row["Complexity_Loss"] * weights["Complexity"])

df_norm["J_Scenario_1"] = df_norm.apply(lambda r: calculate_J(r, weights_scenario_1), axis=1)
df_norm["J_Scenario_2"] = df_norm.apply(lambda r: calculate_J(r, weights_scenario_2), axis=1)

print("Нормовані втрати та Інтегральні оцінки (J):")
print(df_norm.to_string(index=False))
print("\nПереможець Сценарію 1 (Бюджет):", df_norm.loc[df_norm["J_Scenario_1"].idxmin()]["Alternative"])
print("Переможець Сценарію 2 (Надійність):", df_norm.loc[df_norm["J_Scenario_2"].idxmin()]["Alternative"])