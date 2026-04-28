# HRMS AI Chatbot (Llama 3.3 RAG Implementation)

A sophisticated HR Assistant chatbot built with **Django**, **React**, and **Groq Llama 3**, designed for automated employee support and real-time HR data retrieval.

## 🚀 Key Features

- **Multi-Model Intelligence:** Leveraging **Llama-3.3-70b-versatile** via Groq Cloud for ultra-fast, high-reasoning HR support.
- **Dynamic Intent Classification:** Automatically classifies user questions into intents (attendance, leave status, employee summary, etc.) to fetch the correct data from the HRMS database.
- **Role-Based Access Control (RBAC):**
  - **Admins:** Can ask about organization-wide trends and full employee details.
  - **Managers:** Scoped strictly to their direct reports (Direct Reportee visibility).
  - **Employees:** Access limited to their own personal data and general HR help.
- **JSON-Only Response Mode:** Dedicated pipeline for ensuring AI outputs valid JSON for seamless integration with frontend dashboards.
- **Resilient API Handling:** Implements **API Key Rotation** and **Model Fallback** (70B -> 8B) to handle rate limits and high traffic without downtime.

## 🛠️ Technology Stack

- **Backend:** Python / Django / Django Rest Framework (DRF)
- **Frontend:** React / Vite / CSS3 (Floating Chat UI)
- **AI Infrastructure:** 
  - **Groq Cloud API** (Inference Engine)
  - **Llama 3.3 / 3.1** (LLM Models)
- **Security:** JWT-based role authentication and server-side visibility scoping.

## 📂 Project Structure

- `backend/`: Contains the Django app logic.
  - `views.py`: Main API endpoint for chat interaction.
  - `services.py`: The core AI logic, including Groq integration, key rotation, and model fallback.
  - `urls.py`: URL routing for the chatbot API.
- `frontend/`: Contains the React UI.
  - `FloatingChatbot.jsx`: A polished, responsive floating chat interface with real-time feedback.

## 🧠 How it Works

1. **User asks a question** (e.g., "Who in my team is on leave today?").
2. **Intent Classifier:** The system uses a fast LLM pass to classify the question's intent and scope.
3. **Data Retrieval:** Based on the intent, the backend fetches trusted data from the PostgreSQL database (strictly filtered by the user's Role).
4. **Context Injection:** The trusted HR data is injected into a "Format Scoped Answer" prompt.
5. **Final Response:** The AI generates a warm, professional response using the actual data, ensuring zero hallucinations.

---
*Developed as a specialized module for the FirstClick HRMS Unified Platform.*
