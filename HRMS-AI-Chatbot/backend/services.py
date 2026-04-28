import json
import logging
import requests
from decouple import config

logger = logging.getLogger(__name__)

def invoke_groq_chat(system_prompt, user_prompt, history=None):
    """
    Invokes the Groq API with Llama 3 models and key rotation.
    """
    # Collect all available Groq keys for rotation
    api_keys = [
        config("GROQ_API_KEY", default=None),
        config("GROQ_API_KEY_2", default=None),
        config("GROQ_API_KEY_3", default=None)
    ]
    api_keys = [k for k in api_keys if k]
    
    if not api_keys:
        logger.error("No GROQ_API_KEY found in environment.")
        raise RuntimeError("Groq API key is missing. AI Chatbot is disabled.")
    
    url = "https://api.groq.com/openai/v1/chat/completions"
    
    # We use latest Llama models available on Groq
    # Downgrading from 70B to 8B if rate limits hit
    candidate_groq_models = [
        "llama-3.3-70b-versatile",
        "llama-3.1-70b-versatile",
        "llama-3.1-8b-instant"
    ]
    
    messages = [{"role": "system", "content": system_prompt}]
    if history:
        messages.extend([
            {"role": "user" if item.get("role") == "user" else "assistant", "content": item.get("text", "")}
            for item in history if item.get("role") and item.get("text")
        ])
    messages.append({"role": "user", "content": user_prompt})

    last_error = "Unknown error"
    
    # Try each key until one works
    for api_key in api_keys:
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }
        
        # For each key, try the best models first
        for model in candidate_groq_models:
            try:
                payload = {
                    "model": model,
                    "messages": messages,
                    "temperature": 0.2,
                    "max_tokens": 1024
                }
                response = requests.post(url, headers=headers, json=payload, timeout=15)
                
                if response.status_code == 200:
                    data = response.json()
                    return {
                        "answer": data["choices"][0]["message"]["content"].strip(),
                        "model": f"Groq ({model})"
                    }
                
                # If rate limited (429), break to try next key or next model
                if response.status_code == 429:
                    logger.warning(f"Groq Rate Limit (429) hit for key {api_key[:10]} and model {model}")
                    break # Break inner loop to try next key or next model logic
                
                last_error = f"HTTP {response.status_code}: {response.text}"
                logger.warning(f"Groq {model} failed with key {api_key[:10]}: {last_error}")
                
            except Exception as e:
                last_error = str(e)
                logger.error(f"Groq {model} exception with key {api_key[:10]}: {last_error}")
            
    raise RuntimeError(f"All Groq keys/models failed. Last error: {last_error}")


def invoke_chat_model(system_prompt, user_prompt, history=None):
    """
    Main entry point for text-based chat.
    """
    return invoke_groq_chat(system_prompt, user_prompt, history=history)


def invoke_chat_json(system_prompt, user_prompt, history=None):
    """
    Invokes the chat model and ensures the output is valid JSON.
    """
    result = invoke_chat_model(
        system_prompt,
        f"{user_prompt}\n\nReturn valid JSON only.",
        history=history
    )
    answer = result["answer"].strip()
    
    # Clean up markdown code blocks if present
    if answer.startswith("```"):
        lines = answer.split("\n")
        if lines[0].strip().startswith("```"):
            lines = lines[1:]
        if lines[-1].strip() == "```":
            lines = lines[:-1]
        answer = "\n".join(lines).strip()
    
    try:
        return {
            "data": json.loads(answer),
            "model": result["model"],
        }
    except json.JSONDecodeError as e:
        logger.error(f"JSON Decode Error: {str(e)} | Raw output: {answer}")
        raise RuntimeError("Failed to parse AI response as JSON.")


def classify_chat_intent(question, role, has_employee_id=False, history=None):
    system_prompt = (
        "You are an expert HR intent classifier for FirstClick HRMS. "
        "CRITICAL SECURITY RULE: You must honor role-based access limits. "
        "Managers ONLY have access to their reported team. They cannot see organization-wide data. "
        "If a Manager asks a general organizational question, set the scope to 'team'. "
        "Analyze the user question and determine the intent, scope, and timeframe. "
        "Intents:\n"
        "- employee_summary: General details about a specific employee.\n"
        "- employee_pending_requests: Counts of pending items for an employee.\n"
        "- employee_attendance: Detailed attendance logs/status for an employee.\n"
        "- employee_attendance_percentage: Stats like % present for an employee.\n"
        "- leave_today: Who is on leave right now?\n"
        "- attendance_status_list: List of people who are Present/Absent today/yesterday.\n"
        "- today_punch_details: Organization-wide punch in/out times for today.\n"
        "- organization_pending_requests: Totals of pending items across the company.\n"
        "- company_weekends: Which days are weekends?\n"
        "- employee_id_prefix: What is the company's ID prefix?\n"
        "- role_scoped_attendance_percentage: Stats for Admin (Company), Manager (Team), or Self.\n"
        "- team_reportees: List of people reporting to a manager.\n"
        "- access_scope: Questions about what the user can see.\n"
        "- greeting: Hi, Hello, etc.\n"
        "- general_hr_help: How to use the bot?\n"
        "Scopes: self, target_employee, team, organization (Admins only), none.\n"
        "Timeframes: daily, weekly, monthly, yearly, today, yesterday, none.\n\n"
        "Return JSON only: {\"intent\":\"...\", \"scope\":\"...\", \"timeframe\":\"...\", \"status\":\"Absent|Present|etc\", \"suggested_action\": \"/profile|/attendance|none\", \"employee_id\": \"EMP001|none\"}"
    )
    user_prompt = (
        f"User Role: {role}\n"
        f"Has ID in current text: {has_employee_id}\n"
        f"Question: {question}"
    )
    return invoke_chat_json(system_prompt, user_prompt, history=history)


def format_scoped_answer(question, role, payload, history=None):
    system_prompt = (
        "You are FirstClick HR assistant. "
        "SECURITY POLICY: You must follow role-based visibility. "
        "- For Managers: You only have access to your Direct Reportees (the team list provided). "
        "- You CANNOT see or mention any employee outside of your team. "
        "- If a Manager asks about someone else, politely inform them they only have access to their reported team. "
        "Write a concise, professional, and warm answer. "
        "If the user greets you (Hi, Hello, Good Morning, etc.), respond naturally and variedly without being repetitive. "
        "Use the provided trusted data payload for HR questions. "
        "Do not invent facts. If data is empty, say so clearly. "
        "Preserve employee IDs, counts, dates, and attendance percentages exactly."
    )
    user_prompt = (
        f"Role: {role}\n"
        f"Question: {question}\n"
        f"Trusted payload:\n{json.dumps(payload, default=str)}"
    )
    return invoke_chat_model(system_prompt, user_prompt, history=history)

# Keep these for compatibility if needed elsewhere, but they just route to the new system
def invoke_bedrock_chat(system_prompt, user_prompt, history=None):
    return invoke_chat_model(system_prompt, user_prompt, history=history)

def invoke_bedrock_json(system_prompt, user_prompt, history=None):
    return invoke_chat_json(system_prompt, user_prompt, history=history)
