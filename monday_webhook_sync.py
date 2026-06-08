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
    
    # Check if this is a Monday.com event webhook
    if 'event' in webhook_data:
        event = webhook_data['event']
        
        # Extract basic info
        item_name = event.get('pulseName', 'Unnamed Lead')
        pulse_id = event.get('pulseId')
        
        # We need to fetch the full item data from Monday.com
        # because the webhook only sends the changed column
        query = """
        query ($itemId: ID!) {
            items(ids: [$itemId]) {
                id
                name
                column_values {
                    id
                    text
                    value
                }
            }
        }
        """
        
        variables = {"itemId": str(pulse_id)}
        
        try:
            result = monday_api_call(query, variables)
            items = result.get("data", {}).get("items", [])
            
            if not items:
                print(f"Item {pulse_id} not found")
                return {"action": "skipped", "reason": "item not found"}
            
            item = items[0]
            item_name = item.get("name", "Unnamed Lead")
            
            # Extract column values
            email = None
            phone = None
            column_data = {}
            
            for col in item.get("column_values", []):
                col_id = col.get("id")
                col_text = col.get("text")
                col_value = col.get("value")
                
                # Map to our target columns
                if "email" in col_id.lower() or "e-mail" in col_id.lower():
                    email = col_text
                    column_data["email"] = col_text
                elif "phone" in col_id.lower() or "telefoon" in col_id.lower():
                    phone = col_text
                    column_data["phone"] = col_text
                elif "status" in col_id.lower():
                    if col_value:
                        try:
                            value_json = json.loads(col_value)
                            if "label" in value_json:
                                column_data["status"] = value_json["label"].get("text", col_text)
                            else:
                                column_data["status"] = col_text
                        except:
                            column_data["status"] = col_text
                elif col_text:  # Only add if there's actual text
                    # Store other columns by their ID
                    column_data[col_id] = col_text
            
            # Find existing item by email or phone
            existing_item_id = find_existing_item(email, phone)
            
            # Build column values for target board
            column_values = {}
            
            # Map the data to target columns
            if item_name:
                pass  # Name is set separately
            
            if column_data.get("status"):
                column_values["color_mm447yqp"] = json.dumps({"label": column_data["status"]})
            
            if column_data.get("phone"):
                column_values["phone_mm4437rj"] = json.dumps({"phone": column_data["phone"], "countryShortName": "NL"})
            
            if column_data.get("email"):
                column_values["email_mm44bcht"] = json.dumps({"email": column_data["email"], "text": column_data["email"]})
            
            # Add other text columns if they exist
            for col_id, value in column_data.items():
                if col_id not in ["email", "phone", "status"] and value:
                    # Try to map to target columns
                    if "ontruimen" in col_id.lower():
                        column_values["text_mm44f127"] = value
                    elif "termijn" in col_id.lower():
                        column_values["text_mm44qvrx"] = value
                    elif "plaats" in col_id.lower():
                        column_values["text_mm4485z4"] = value
                    elif "tekst" in col_id.lower():
                        column_values["long_text_mm445fwr"] = json.dumps({"text": value})
                    elif "opvolging" in col_id.lower():
                        column_values["text_mm446bsd"] = value
            
            column_values_json = json.dumps(column_values)
            
            if existing_item_id:
                # Update existing item
                print(f"Updating existing item: {existing_item_id} - {item_name}")
                
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
                # Create new item
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
                
        except Exception as e:
            print(f"Error fetching item data: {e}")
            return {"action": "error", "error": str(e)}
    
    else:
        # Old format (direct column mapping)
        item_name = webhook_data.get("name", "Unnamed Lead")
        email = webhook_data.get("email")
        phone = webhook_data.get("phone")
        
        existing_item_id = find_existing_item(email, phone)
        
        column_values = {}
        for source_col, target_col in COLUMN_MAPPING.items():
            if source_col in webhook_data and webhook_data[source_col]:
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
