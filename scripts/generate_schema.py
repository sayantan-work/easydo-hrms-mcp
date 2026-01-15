"""
Generate database schema from production/staging database via n8n webhook.
Usage: python scripts/generate_schema.py [prod|staging]
"""
import json
import os
import requests
import sys
from datetime import datetime
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Webhook URLs (from .env)
WEBHOOKS = {
    "prod": os.getenv("N8N_WEBHOOK_PROD"),
    "staging": os.getenv("N8N_WEBHOOK_STAGING")
}

def execute_query(webhook_url: str, query: str) -> list:
    """Execute SQL query via n8n webhook."""
    response = requests.post(
        webhook_url,
        json={"query": query, "params": []},
        headers={"Content-Type": "application/json"},
        timeout=60
    )
    result = response.json()
    if result.get("success"):
        return result.get("data", [])
    raise Exception(result.get("error", "Query failed"))

def generate_schema(env: str = "prod"):
    """Generate schema for the specified environment."""
    webhook_url = WEBHOOKS.get(env)
    if not webhook_url:
        print(f"Invalid environment: {env}. Use 'prod' or 'staging'")
        sys.exit(1)

    print(f"Generating schema for {env.upper()}...")
    print(f"Using webhook: {webhook_url[:50]}...")

    # Get all tables
    print("Fetching tables...")
    tables_query = """
        SELECT table_name
        FROM information_schema.tables
        WHERE table_schema = 'public' AND table_type = 'BASE TABLE'
        ORDER BY table_name
    """
    tables = execute_query(webhook_url, tables_query)
    print(f"Found {len(tables)} tables")

    schema = {
        "_metadata": {
            "environment": env,
            "generated_at": datetime.now().isoformat(),
            "table_count": len(tables)
        }
    }

    # Get columns for each table
    for i, table in enumerate(tables):
        table_name = table['table_name']
        print(f"[{i+1}/{len(tables)}] Processing {table_name}...")

        columns_query = f"""
            SELECT column_name, data_type, is_nullable, column_default, character_maximum_length
            FROM information_schema.columns
            WHERE table_name = '{table_name}' AND table_schema = 'public'
            ORDER BY ordinal_position
        """
        columns = execute_query(webhook_url, columns_query)

        schema[table_name] = {
            "columns": [
                {
                    "name": col["column_name"],
                    "type": col["data_type"],
                    "nullable": col["is_nullable"] == "YES",
                    "default": col.get("column_default"),
                    "max_length": col.get("character_maximum_length")
                }
                for col in columns
            ]
        }

    # Save to file
    output_path = f"api/schema/{env}_database_schema.json"
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(schema, f, indent=2, default=str)

    print(f"\nSchema saved to {output_path}")
    print(f"Total tables: {len(tables)}")

if __name__ == "__main__":
    env = sys.argv[1] if len(sys.argv) > 1 else "prod"
    generate_schema(env)
