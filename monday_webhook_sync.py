#!/usr/bin/env python3
"""
Monday.com Webhook Synchronisatie Script
Synchroniseert leads van rocketleads-team naar Verhuisvlot CRM

Functionaliteit:
- Ontvangt webhook van bron-board
- Checkt of lead al bestaat (op basis van email)
- Update bestaand item OF creëert nieuw item
- Voorkomt duplicaten
"""

import os
import json
import requests
from flask import Flask, request, jsonify

app = Flask(__name__)

# Monday.com API configuratie
MONDAY_API_URL = "https://api.monday.com/v2"
MONDAY_API_TOKEN = "eyJhbGciOiJIUzI1NiJ9.eyJ0aWQiOjY2ODA0NjE0MCwiYWFpIjoxMSwidWlkIjoxMDQ5NzMxODUsImlhZCI6IjIwMjYtMDYtMDhUMDg6MzU6MzguMDAwWiIsInBlciI6Im1lOndyaXRlIiwiYWN0aWQiOjM1NDg2NDQwLCJyZ24iOiJldWMxIn0.JS_-42yqYGI7Xu7DDcZMFfwiu-cNOEbUna1qBvMC3ZQ"
TARGET_BOARD_ID = "5098088814"  # Verhuisvlot Leads (Geïmporteerd)

# Kolom mapping: bron kolom ID -> doel kolom ID
COLUMN_MAPPING = {
    "name": "name",
    "status": "color_mm447yqp",
    "phone": "phone_mm4437rj",
    "email": "email_mm44bcht",
    "ontruimen": "text_mm44f127",
    "termijn": "text_mm44qvrx",
    "plaats": "text_mm4485z4",
    "straat_huisnummer": "text_mm44crfe",
    "postcode": "text_mm44ewk3",
    "wat_ontruimen": "long_text_mm44q5vv",
    "date_created": "date_mm44y0cy",
    "first_contact": "date_mm44qr47",
    "advertentie_utm": "text_mm4450qm",
    "tekst": "long_text_mm445fwr",
    "opvolging_door": "text_mm446bsd"
}


def monday_api_call(query, variables=None):
    """Voer een Monday.com API call uit"""
    headers = {
        "Authorization": MONDAY_API_TOKEN,
        "Content-Type": "application/json"
    }
    
    data = {"query": query}
    if variables:
        data["variables"] = variables
    
    response = requests.post(MONDAY_API_URL, json=data, headers=headers)
    
    if response.status_code != 200:
        raise Exception(f"API call failed: {response.status_code} - {response.text}")
    
    return response.json()


def find_existing_item(email, phone):
    """Zoek bestaand item op basis van email of telefoon"""
    if not email and not phone:
        return None
    
    # Query om items te zoeken op email
    query = """
    query ($boardId: ID!, $columnId: String!, $value: String!) {
        items_page_by_column_values(
            board_id: $boardId
            columns: [{column_id: $columnId, column_values: [$value]}]
            limit: 1
        ) {
            items {
                id
                name
            }
        }
    }
    """
    
    # Probeer eerst op email
    if email:
        variables = {
            "boardId": TARGET_BOARD_ID,
            "columnId": "email_mm44bcht",
            "value": email
        }
        
        try:
            result = monday_api_call(query, variables)
            items = result.get("data", {}).get("items_page_by_column_values", {}).get("items", [])
            if items:
                return items[0]["id"]
        except Exception as e:
            print(f"Error searching by email: {e}")
    
    # Als geen match op email, probeer telefoon
    if phone:
        variables = {
            "boardId": TARGET_BOARD_ID,
            "columnId": "phone_mm4437rj",
            "value": phone
        }
        
        try:
            result = monday_api_call(query, variables)
            items = result.get("data", {}).get("items_page_by_column_values", {}).get("items", [])
            if items:
                return items[0]["id"]
        except Exception as e:
            print(f"Error searching by phone: {e}")
    
    return None


def format_column_value(column_type, value):
    """Formatteer kolom waarde op basis van type"""
    if not value:
        return None
    
    # Status kolom
    if column_type == "status":
        return json.dumps({"label": value})
    
    # Phone kolom
    elif column_type == "phone":
        return json.dumps({"phone": value, "countryShortName": "NL"})
    
    # Email kolom
    elif column_type == "email":
        return json.dumps({"email": value, "text": value})
    
    # Date kolom
    elif column_type == "date":
        return json.dumps({"date": value})
    
    # Long text kolom
    elif column_type == "long_text":
        return json.dumps({"text": value})
    
    # Text kolom (gewoon string)
    else:
        return value


def create_or_update_item(webhook_data):
    """Creëer of update een item in het doel-board"""
    
    # Extract data uit webhook
    item_name = webhook_data.get("name", "Unnamed Lead")
    email = webhook_data.get("email")
    phone = webhook_data.get("phone")
    
    # Zoek bestaand item
    existing_item_id = find_existing_item(email, phone)
    
    # Bouw column values
    column_values = {}
    for source_col, target_col in COLUMN_MAPPING.items():
        if source_col in webhook_data and webhook_data[source_col]:
            # Bepaal kolom type op basis van target kolom ID
            if "color_" in target_col:
                col_type = "status"
            elif "phone_" in target_col:
                col_type = "phone"
            elif "email_" in target_col:
                col_type = "email"
            elif "date_" in target_col:
                col_type = "date"
            elif "long_text_" in target_col:
                col_type = "long_text"
            else:
                col_type = "text"
            
            formatted_value = format_column_value(col_type, webhook_data[source_col])
            if formatted_value:
                column_values[target_col] = formatted_value
    
    column_values_json = json.dumps(column_values)
    
    if existing_item_id:
        # Update bestaand item
        print(f"Updating existing item: {existing_item_id}")
        
        mutation = """
        mutation ($boardId: ID!, $itemId: ID!, $columnValues: JSON!) {
            change_multiple_column_values(
                board_id: $boardId
                item_id: $itemId
                column_values: $columnValues
            ) {
                id
                name
            }
        }
        """
        
        variables = {
            "boardId": TARGET_BOARD_ID,
            "itemId": existing_item_id,
            "columnValues": column_values_json
        }
        
        result = monday_api_call(mutation, variables)
        return {
            "action": "updated",
            "item_id": existing_item_id,
            "item_name": item_name
        }
    
    else:
        # Creëer nieuw item
        print(f"Creating new item: {item_name}")
        
        mutation = """
        mutation ($boardId: ID!, $itemName: String!, $columnValues: JSON!) {
            create_item(
                board_id: $boardId
                item_name: $itemName
                column_values: $columnValues
            ) {
                id
                name
            }
        }
        """
        
        variables = {
            "boardId": TARGET_BOARD_ID,
            "itemName": item_name,
            "columnValues": column_values_json
        }
        
        result = monday_api_call(mutation, variables)
        new_item = result.get("data", {}).get("create_item", {})
        
        return {
            "action": "created",
            "item_id": new_item.get("id"),
            "item_name": item_name
        }


@app.route('/webhook', methods=['POST', 'GET'])
def webhook_handler():
    """Webhook endpoint die Monday.com data ontvangt"""
    
    try:
        # Handle Monday.com challenge verification
        if request.method == 'GET':
            challenge = request.args.get('challenge')
            if challenge:
                return jsonify({"challenge": challenge}), 200
        
        # Parse webhook data
        webhook_data = request.json
        
        # Handle Monday.com challenge in POST body
        if 'challenge' in webhook_data:
            return jsonify({"challenge": webhook_data['challenge']}), 200
        
        print(f"Received webhook: {json.dumps(webhook_data, indent=2)}")
        
        # Verwerk de data
        result = create_or_update_item(webhook_data)
        
        return jsonify({
            "success": True,
            "result": result
        }), 200
    
    except Exception as e:
        print(f"Error processing webhook: {e}")
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500
        
        print(f"Received webhook: {json.dumps(webhook_data, indent=2)}")
        
        # Verwerk de data
        result = create_or_update_item(webhook_data)
        
        return jsonify({
            "success": True,
            "result": result
        }), 200
    
    except Exception as e:
        print(f"Error processing webhook: {e}")
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500


@app.route('/health', methods=['GET'])
def health_check():
    """Health check endpoint"""
    return jsonify({"status": "healthy"}), 200


if __name__ == '__main__':
    # Start de Flask server
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=True)
