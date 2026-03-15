# 🤖 Step-by-Step AI Chatbot Integration

To add an AI chatbot to your ANPR Streamlit app, we can use Streamlit's built-in chat UI (`st.chat_message`). 

Here are the manual steps if you'd like to understand the process, or I can implement this for you automatically!

### Step 1: Get an API Key
You will need an AI provider. **Google Gemini** offers a free tier that is excellent for this.
1. Go to [Google AI Studio](https://aistudio.google.com/) and get an API key.
2. Add it to your `.env` file: `GEMINI_API_KEY=your_key_here`

### Step 2: Install the AI Library
Run this in your terminal:
```bash
pip install google-generativeai
```

### Step 3: Add to `streamlit_app.py`
We will add a new page function that utilizes `google.generativeai` and Streamlit's chat history.

```python
import google.generativeai as genai

def page_assistant():
    st.markdown("## 💬 AI Assistant")
    st.caption("Ask questions about the ANPR system, your history, or how detection works!")
    
    # Configure API
    genai.configure(api_key=os.getenv("GEMINI_API_KEY"))
    model = genai.GenerativeModel('gemini-1.5-flash')
    
    # Initialize chat history in session state
    if "messages" not in st.session_state:
        st.session_state.messages = [
            {"role": "assistant", "content": "Hi! I'm the ANPR AI Assistant. How can I help you today?"}
        ]
        
    # Display existing messages
    for msg in st.session_state.messages:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])
            
    # Handle new user input
    if prompt := st.chat_input("Ask me anything about the ANPR system..."):
        # Display user message
        with st.chat_message("user"):
            st.markdown(prompt)
        st.session_state.messages.append({"role": "user", "content": prompt})
        
        # System Context to make the AI smart about your specific project
        system_context = "You are a helpful assistant for an ANPR (Automatic Number Plate Recognition) system built with Flask, MySQL, YOLOv8, and Streamlit..."
        full_prompt = f"{system_context}\n\nUser: {prompt}"
        
        # Get AI Response
        with st.chat_message("assistant"):
            with st.spinner("Thinking..."):
                try:
                    response = model.generate_content(full_prompt)
                    st.markdown(response.text)
                    st.session_state.messages.append({"role": "assistant", "content": response.text})
                except Exception as e:
                    st.error(f"Error connecting to AI: {e}")
```

### Step 4: Add to the Sidebar
Finally, we just add the `page_assistant` to the sidebar so users can click it.
```python
# In the sidebar() function:
_nav("💬 AI Assistant", "assistant")

# In the PAGE_MAP dictionary at the bottom:
"assistant": page_assistant,
```

---
**Would you like me to implement this for you? I just need to know which AI provider (Gemini, OpenAI, etc.) you want to use!**
