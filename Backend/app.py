import eventlet
eventlet.monkey_patch()

import re
from typing import Optional, TypedDict, List
from langgraph.graph import StateGraph, START, END
from langchain.chains import LLMChain
from langchain.prompts import PromptTemplate
from langchain_openai import ChatOpenAI
import dotenv
import json
from flask import Flask, request
from flask_socketio import SocketIO, emit, join_room
import uuid
import queue
from flask_cors import CORS


dotenv.load_dotenv()

app = Flask(__name__)
CORS(app)
socketio = SocketIO(app, 
                   cors_allowed_origins="*", 
                   async_mode='eventlet',
                   logger=True,  # Add logging
                   engineio_logger=True)  # Add engine.io logging
# ------------------- Existing Core Logic -------------------
def clean_json_response(response: str) -> str:
    match = re.search(r"```json(.*?)```", response.strip(), re.DOTALL)
    return match.group(1).strip() if match else response

class ShippingWorkflowState(TypedDict):
    personal_detail: Optional[dict]
    more_3: Optional[dict]
    less_3: Optional[dict]

store = {}

def get_by_session_id(session_id: str) -> List[str]:
    if session_id not in store:
        store[session_id] = []
    return store[session_id]


def is_complete_personal_detail(state: ShippingWorkflowState) -> bool:
    personal_detail = all(state["personal_detail"].get(field) for field in ["full_name", "company_name", "company_address", "phone_number", "email","number_of_containers"])


    return  personal_detail

def is_complete_more3(state: ShippingWorkflowState) -> bool:
    required_fields = [ "size", "empty_or_loaded", "pickup_address", "delivery_address"]
    
    # Check if all required fields are present
    if not all(state["more_3"].get(field) for field in required_fields):
        return False
    
    # Check if all elements in the lists are present
    for field in ["size", "empty_or_loaded", "pickup_address", "delivery_address"]:
        if any(not item for item in state["more_3"].get(field, [])):
            return False
    
    return True



def is_complete_less3(state: ShippingWorkflowState) -> bool:
    required_fields = [ "used_service_before", "size", "empty_or_loaded", "hazardous", "new_customer", "pickup_address", "lifting_setup", "container_door_opening_pickup", "pickup_surface_type", "pickup_location_grade", "delivery_address", "dropping_setup", "container_door_opening_drop_off","drop_off_surface_type","drop_off_location_grade"]
    
    # Check if all required fields are present
    if not all(state["less_3"].get(field) for field in required_fields):
        return False
    
    # Check if all elements in the lists are present
    for field in ["size", "empty_or_loaded", "hazardous", "new_customer", "pickup_address", "lifting_setup", "container_door_opening_pickup", "pickup_surface_type", "pickup_location_grade", "delivery_address", "dropping_setup", "container_door_opening_drop_off","drop_off_surface_type","drop_off_location_grade"]:
        if any(not item for item in state["less_3"].get(field, [])):
            return False
    
    return True

# Initialize LLM
llm = ChatOpenAI(model="gpt-4o")

# Prompt template to ask the user for missing information.
question_prompt_personal_detail = PromptTemplate(
    input_variables=["history", "current_state"],
    template=(
        """
        History:
        {history}
        This is my current data from the user:
        {current_state}
        1. The user has provided some details. Update the state if needed.
        2. Please ask for the missing information in the order of the fields.
        3. Ask in natural conversation flow
        4. Group similar questions when possible. 
        5. Keep the history of the chat in mind when asking the next question.
        6. The conversational can deviate from the expected flow. Be prepared to handle that.
        7. After a few interactions if the conversation is deviating, try to bring it back on track but in a way that feels natural.
        State description:
        [
            full_name: [first name, last name (optional)]
            company_name: [Company name where the user works]
            company_address: [Company address of the user's company]
            phone_number: [Phone number of the user]
            email: [Email address of the user]
            number_of_containers: [Number of containers the user wants to ship]
        ]
        
        Your response should only contain the question you want to ask.
        """
    )
)

# Prompt template to update the state based on the user's response.
state_update_prompt_personal_detail = PromptTemplate(
    input_variables=["history", "current_state", "question", "response"],
    template=(
        """
        History:
        {history}
        This is my current data from the user:
        {current_state}

        The user provided the following response to the question:
        Question: {question}
        Response: {response}

        Your tasks are:
        1. Update the state with the new information provided. If there is conflicting info, prioritize the new input.
        2. If the user asked a question or needs clarification, provide a friendly answer.
        3. User may ask some questions which have their answers in the history. You can use the history to answer those questions.

        State description:
        [
            full_name: [first name, last name (optional)]
            company_name: [Company name where the user works]
            company_address: [Company address of the user's company]
            phone_number: [Phone number of the user]
            email: [Email address of the user]
        ]

        Output Format:
        {{
            "updated_state": {{
                "full_name": "...",
                "company_name": "...",
                "company_address": "...",
                "phone_number": "...",
                "email": "...",
                "number_of_containers": "..."
            }},
            "response": "Your response to the user here."
        }}
        Output only the JSON object.
        """
    )
)


# Prompt template to ask the user for missing information.
question_prompt_more3 = PromptTemplate(
    input_variables=["history", "current_state"],
    template=(
        """
        History:
        {history}
        This is my current data from the user:
        {current_state}
        1. The user has provided some details. Update the state if needed.
        2. Please ask for the missing information in the order of the fields.
        3. Ask in natural conversation flow
        4. Group similar questions when possible. 
        5. Keep the history of the chat in mind when asking the next question.
        6. The conversational can deviate from the expected flow. Be prepared to handle that.
        7. After a few interactions if the conversation is deviating, try to bring it back on track but in a way that feels natural.
        
        State description:
        [
            size: [Size of the containers. If number_of_containers = 3, this will be a list of 3 elements]
            empty_or_loaded: [Empty or loaded status of the containers. If number_of_containers = 3, this will be a list of 3 elements]
            pickup_address: [Pickup address for the containers. If number_of_containers = 3, this will be a list of 3 elements]
            delivery_address: [Delivery address for the containers. If number_of_containers = 3, this will be a list of 3 elements]
        ]
        
        Your response should only contain the question you want to ask.
        """
    )
)

# Prompt template to update the state based on the user's response.
state_update_prompt_more3 = PromptTemplate(
    input_variables=["history", "current_state", "question", "response"],
    template=(
        """
        History:
        {history}
        This is my current data from the user:
        {current_state}

        The user provided the following response to the question:
        Question: {question}
        Response: {response}

        Your tasks are:
        1. Update the state with the new information provided. If there is conflicting info, prioritize the new input.
        2. If the user asked a question or needs clarification, provide a friendly answer.
        3. User may ask some questions which have their answers in the history. You can use the history to answer those questions.

        State description:
        [
            number_of_containers: [Number of containers the user wants to ship]
            size: [Size of the containers. If number_of_containers = 3, this will be a list of 3 elements]
            empty_or_loaded: [Empty or loaded status of the containers. For example if number_of_containers = 3, this will be a list of 3 elements]
            pickup_address: [Pickup address for the containers. For example if number_of_containers = 3, this will be a list of 3 elements]
            delivery_address: [Delivery address for the containers. For example if number_of_containers = 3, this will be a list of 3 elements]
        ]

        Output Format:
        {{
            "updated_state": {{
                "size": ["...", "...", "..."],
                "empty_or_loaded": ["...", "...", "..."],
                "pickup_address": ["...", "...", "..."],
                "delivery_address": ["...", "...", "..."]
            }},
            "response": "Your response to the user here."
        }}

        Output only the JSON object.
        """
    )
)



# Less than 3 Containers - Asking Question
question_prompt_less3 = PromptTemplate(
    input_variables=["history", "current_state"],
    template=(
        """
History:
{history}
Current container details:
{current_state}

We still need more information to complete your request. Please ask for the missing details in the following order.
Ask in natural conversation flow. Use these guidelines:

State fields:
- used_service_before: Have you used our service before? 
  - If Yes, say: "Before we proceed, I recommend reviewing our requirements page to ensure all containers meet our safety standards for transport. This includes restrictions on overhangs or protrusions and proper corner castings. Do all your containers meet these criteria? If not, I’d be happy to guide you through our requirements. Please choose one of the two options."
  - If No, say: "I recommend reviewing our full requirements page to better understand our services, as we are not your typical container transport company. This should help clarify our offerings. Feel free to ask if you have any questions during the quote process."
- size: Provide the size for each container (list).
- empty_or_loaded: Indicate if each container is empty or loaded (list).
- hazardous: Are you transporting any hazardous or combustible materials (e.g., propane, paint, etc.)? If none, respond "No." If yes, please specify. If yes, then add: "Thank you for letting me know about the propane tanks. I’ll note that. Is there anything else hazardous in your shipment?"
- new_customer: Are you a new customer?
- corner_casting: If new_customer is Yes, ask: "Does your container have the universal 5/8 inch corner castings in good condition without major dents or defects? Thank you – could you provide more details on their condition?"
- protrusions_end_or_top: If new_customer is Yes, ask: "Does your container have any protrusions on the ends or top (e.g., air conditioning units, brackets, metal signage, or electrical boxes)? Thank you – if there’s a protrusion on top, we may have safety concerns, but it's case-specific. If possible, please send photos later via email."
- protrusions_long_side: If new_customer is Yes, ask: "Do either of the long sides of your container have any protrusions (like air conditioning units, brackets, metal signage, or electrical boxes)? If yes, please describe them. If not, ask: 'Is there any additional information we should know about the container or its contents?'"
- pickup_address: The pickup address (list).
- lifting_setup: Describe the lifting setup (e.g., right/left side load/unload and options like 20, 40, or 60 feet). If unsure, say: "No problem, I understand. These guidelines are flexible, and we know every setup is unique. Let's continue and we can follow up later if needed. You may also send photos later."
- container_door_opening_pickup: If applicable, ask: "Which way does the container door open? Please choose one: [A - towards the truck cabin, B - Right side, C - behind the truck, D - Left side]. If unsure, feel free to skip."
- pickup_surface_type: What is the type of surface at the pickup location? (e.g., concrete, asphalt, grass, or dirt)
- pickup_location_grade: What is the approximate grade of the pickup location? If unsure, choose one: Flat Surface, Mild incline, or Steep Incline.
- delivery_address: The delivery address or coordinates (list).
- dropping_setup: Describe the dropping setup (similar to lifting setup). If unsure, say: "No problem, I understand. Let's continue and follow up later if needed."
- container_door_opening_drop_off: If applicable, ask: "Which way does the container door open at drop-off? Please choose one: [A - towards the truck cabin, B - Right side, C - behind the truck, D - Left side]. You may skip if unsure."
- drop_off_surface_type: What type of surface will the container be placed on upon delivery? (e.g., concrete, asphalt, grass, or dirt)
- drop_off_location_grade: What is the approximate grade of the drop-off location? If unsure, choose one: Flat Surface, Mild incline, or Steep Incline.

Keep your question clear, friendly, and natural.

Your response should only contain the question you want to ask.
        """
    )
)

# Less than 3 Containers - Updating State
state_update_prompt_less3 = PromptTemplate(
    input_variables=["history", "current_state", "question", "response"],
    template=(
        """
History:
{history}
Current container details:
{current_state}

The user responded to the question:
Question: {question}
Response: {response}

Please update the container details with the new information. Use the latest input if there’s any conflict.
If the user asked for clarifications, provide a friendly answer and refer to the conversation history if needed.

State fields (with guidelines):
- used_service_before: Have you used our service before? 
  - If Yes, respond with: "Before we proceed, I recommend reviewing our requirements page to ensure all containers meet our safety standards for transport. This includes restrictions on overhangs, protrusions, and proper corner castings. Do all your containers meet these criteria? If not, I’d be happy to guide you through our requirements. Please choose one of the two options."
  - If No, respond with: "I recommend reviewing our full requirements page to better understand our services, as we are not your typical container transport company. This should help clarify our offerings. Feel free to ask if you have any questions during the quote process."
- size: The size for each container (list).
- empty_or_loaded: The status of each container (list). if empty then make hazardous as No.
- hazardous: Any hazardous materials being transported (if yes, thank the user and ask if there’s anything else hazardous).
- new_customer: Information on whether you are a new customer.
- corner_casting: If new_customer is Yes, ask: "Does your container have the universal 5/8 inch corner castings in good condition without major dents or defects? Thank you – could you provide more details on their condition?"
- protrusions_end_or_top: If new_customer is Yes, ask: "Does your container have any protrusions on the ends or top (e.g., air conditioning units, brackets, metal signage, or electrical boxes)? Thank you – if there’s a protrusion on top, we may have safety concerns, but it's case-specific. If possible, please send photos later via email."
- protrusions_long_side: If new_customer is Yes, ask: "Do either of the long sides of your container have any protrusions (like air conditioning units, brackets, metal signage, or electrical boxes)? If yes, please describe them. If not, ask: 'Is there any additional information we should know about the container or its contents?'"
- pickup_address: The pickup address (list).
- lifting_setup: The lifting setup details (list).
- container_door_opening_pickup: The container door opening direction for pickup (list).
- pickup_surface_type: The surface type at pickup (list).
- pickup_location_grade: The pickup location grade (list).
- delivery_address: The delivery address or coordinates (list).
- dropping_setup: The dropping setup details (list).
- container_door_opening_drop_off: The container door opening direction at drop-off (list).
- drop_off_surface_type: The surface type at drop-off (list).
- drop_off_location_grade: The drop-off location grade (list).

Output Format:
{{
    "updated_state": {{
        "used_service_before": "...",
        "size": ["...", "..."],
        "empty_or_loaded": ["...", "..."],
        "hazardous": ["...", "..."],
        "new_customer": ["...", "..."],
        "corner_casting": ["...", "..."],
        "protrusions_end_or_top": ["...", "..."],
        "protrusions_long_side": ["...", "..."],
        "pickup_address": ["...", "..."],
        "lifting_setup": ["...", "..."],
        "container_door_opening_pickup": ["...", "..."],
        "pickup_surface_type": ["...", "..."],
        "pickup_location_grade": ["...", "..."],
        "delivery_address": ["...", "..."],
        "dropping_setup": ["...", "..."],
        "container_door_opening_drop_off": ["...", "..."],
        "drop_off_surface_type": ["...", "..."],
        "drop_off_location_grade": ["...", "..."]
    }},
    "response": "Your response to the user here."
}}

Output only the JSON object.
        """
    )
)

def route_after_ask_personal_detail(state: ShippingWorkflowState) -> str:
    # print("in route_after_ask_personal_detail")
    if is_complete_personal_detail(state):
        if int(state["personal_detail"]["number_of_containers"]) >= 3:
            return "more_than_3_ask"
        else:
            return "less_than_3_ask"
    else:
        return "process_answer"
    

def route_after_process_personal_detail(state: ShippingWorkflowState) -> str:
    # print("in route_after_process_personal_detail")
    if is_complete_personal_detail(state):
        if int(state["personal_detail"]["number_of_containers"]) >= 3:
            return "more_than_3_ask"
        else:
            return "less_than_3_ask"
    else:
        return "ask_question"

def route_after_ask_more3(state: ShippingWorkflowState) -> str:
    return "workflow_complete" if is_complete_more3(state) else "more_than_3_process"

def route_after_process_more3(state: ShippingWorkflowState) -> str:
    return "workflow_complete" if is_complete_more3(state) else "more_than_3_ask"

def route_after_ask_less3(state: ShippingWorkflowState) -> str:
    return "workflow_complete" if is_complete_less3(state) else "less_than_3_process"

def route_after_process_less3(state: ShippingWorkflowState) -> str:
    return "workflow_complete" if is_complete_less3(state) else "less_than_3_ask"

def workflow_complete_node(state: ShippingWorkflowState) -> ShippingWorkflowState:
    print("Workflow completed.")
    print("Final state:", state)
    return state

# ------------------- WebSocket Setup -------------------


# Session Management
class SessionManager:
    def __init__(self):
        self.sessions = {}
        
    def create_session(self, sid):
        session_id = str(uuid.uuid4())
        self.sessions[session_id] = {
            'workflow': None,
            'state': self.initial_state(),
            'queue': queue.Queue(),
            'task': None,
            'current_question': None
        }
        self.initialize_workflow(session_id)
        return session_id

    def initial_state(self):
        return {
            "personal_detail": {
                "full_name": None,
                "company_name": None,
                "company_address": None,
                "phone_number": None,
                "email": None,
                "number_of_containers": None
            },
            "more_3": {
                "number_of_containers": None,
                "size": None,
                "empty_or_loaded": None,
                "pickup_address": None,
                "delivery_address": None
            },
            "less_3": {
                "number_of_containers": None,
                "used_service_before": None,
                "size": None,
                "empty_or_loaded": None,
                "hazardous": None,
                "new_customer": None,
                "corner_casting": None,
                "protrusions_end_or_top": None,
                "protrusions_long_side": None,
                "pickup_address": None,
                "lifting_setup": None,
                "container_door_opening_pickup": None,
                "pickup_surface_type": None,
                "pickup_location_grade": None,
                "delivery_address": None,
                "dropping_setup": None,
                "container_door_opening_drop_off": None,
                "drop_off_surface_type": None,
                "drop_off_location_grade": None
            }
        }

    def initialize_workflow(self, session_id):
        workflow = StateGraph(ShippingWorkflowState)
        # --- Conditional Routing Functions ---
        

        # --- Build the LangGraph State Graph ---
        workflow = StateGraph(ShippingWorkflowState)
        workflow.add_node("ask_question", ask_question_node)
        workflow.add_node("process_answer", process_answer_node)
        workflow.add_node("more_than_3_ask", ask_question_node)
        workflow.add_node("more_than_3_process", process_answer_node)
        workflow.add_node("less_than_3_ask", ask_question_node)
        workflow.add_node("less_than_3_process", process_answer_node)

        workflow.add_node("workflow_complete", workflow_complete_node)

        workflow.add_edge(START, "ask_question")
        workflow.add_conditional_edges(
            "ask_question",
            route_after_ask_personal_detail,
            {"workflow_complete": "workflow_complete", "process_answer": "process_answer", "more_than_3_ask": "more_than_3_ask", "less_than_3_ask": "less_than_3_ask"}
        )
        workflow.add_conditional_edges(
            "process_answer",
            route_after_process_personal_detail,
            {"workflow_complete": "workflow_complete", "ask_question": "ask_question", "more_than_3_ask": "more_than_3_ask", "less_than_3_ask": "less_than_3_ask"}
        )

        workflow.add_conditional_edges(
            "more_than_3_ask",
            route_after_ask_more3,
            {"workflow_complete": "workflow_complete", "more_than_3_process": "more_than_3_process"}
        )

        workflow.add_conditional_edges(
            "more_than_3_process",
            route_after_process_more3,
            {"workflow_complete": "workflow_complete", "more_than_3_ask": "more_than_3_ask"}
        )

        workflow.add_conditional_edges(
            "less_than_3_ask",
            route_after_ask_less3,
            {"workflow_complete": "workflow_complete", "less_than_3_process": "less_than_3_process"}
        )

        workflow.add_conditional_edges(
            "less_than_3_process",
            route_after_process_less3,
            {"workflow_complete": "workflow_complete", "less_than_3_ask": "less_than_3_ask"}
        )



        workflow.add_edge("workflow_complete", END)
        self.sessions[session_id]['workflow'] = workflow.compile()

manager = SessionManager()

# ------------------- WebSocket Handlers -------------------
@socketio.on('connect')
def handle_connect():
    print(f"Client connecting: {request.sid}")
    print(f"Client connecting from: {request.remote_addr}")
    print(f"Client headers: {request.headers}")
    print(f"Client sid: {request.sid}")
    sid = request.sid
    session_id = manager.create_session(sid)
    join_room(session_id)
    emit('session_created', {'session_id': session_id})
    socketio.start_background_task(run_workflow, app, session_id)  # Pass app here

@socketio.on('disconnect')
def handle_disconnect():
    sid = request.sid
    print(f"Client disconnected: {sid}")

@socketio.on('user_response')
def handle_user_response(data):
    session_id = data['session_id']
    response = data['response']
    if session_id in manager.sessions:
        manager.sessions[session_id]['queue'].put(response)

# ------------------- Modified Workflow Functions -------------------
from flask import current_app

def run_workflow(app, session_id):  # Add app as a parameter
    try:
        with app.app_context():  # Use app.app_context() instead of current_app
            print(f"Starting workflow for session: {session_id}")
            session = manager.sessions[session_id]
            workflow = session['workflow']
            state = session['state']
            
            while True:
                print(f"Current state: {state}")
                state = workflow.invoke(state)
                print(f"Updated state: {state}")
                
                if is_complete_personal_detail(state) and \
                   (is_complete_more3(state) or is_complete_less3(state)):
                    print("Workflow completed successfully")
                    emit('workflow_complete', {'state': state}, room=session_id)
                    break
    except Exception as e:
        with app.app_context():  # Use app.app_context() instead of current_app
            print(f"Error in workflow for session {session_id}: {str(e)}")
            emit('error', {'error': str(e)}, room=session_id)

# ------------------- Node Implementations -------------------
def ask_question_node(state: ShippingWorkflowState, session_id: str):
    with current_app.app_context():  # Push application context
        history = get_by_session_id(session_id)
        history_str = "\n".join(history)
        print("in ask_question_node")
        print(state)
        
        if not is_complete_personal_detail(state):
            prompt = question_prompt_personal_detail.format(
                history=history_str, 
                current_state=state["personal_detail"]
            )
        elif state["personal_detail"]["number_of_containers"] >= 3:
            prompt = question_prompt_more3.format(
                history=history_str,
                current_state=state["more_3"]
            )
        else:
            prompt = question_prompt_less3.format(
                history=history_str,
                current_state=state["less_3"]
            )
            
        response = LLMChain(llm=llm, prompt=prompt).run({
            "history": history_str,
            "current_state": state
        })
        
        manager.sessions[session_id]['current_question'] = response
        emit('question', {'question': response}, room=session_id)
        history.append(f"System: {response}")
        return state

def process_answer_node(app, state: ShippingWorkflowState, session_id: str):
    with app.app_context():  # Use app.app_context()
        session = manager.sessions[session_id]
        history = get_by_session_id(session_id)
        history_str = "\n".join(history)
        
        try:
            user_input = session['queue'].get(timeout=300)
        except queue.Empty:
            raise TimeoutError("No response received within 5 minutes")
        
        current_question = session['current_question']
        
        if not is_complete_personal_detail(state):
            prompt = state_update_prompt_personal_detail.format(
                history=history_str,
                current_state=state["personal_detail"],
                question=current_question,
                response=user_input
            )
        elif state["personal_detail"]["number_of_containers"] >= 3:
            prompt = state_update_prompt_more3.format(
                history=history_str,
                current_state=state["more_3"],
                question=current_question,
                response=user_input
            )
        else:
            prompt = state_update_prompt_less3.format(
                history=history_str,
                current_state=state["less_3"],
                question=current_question,
                response=user_input
            )
            
        response = LLMChain(llm=llm, prompt=prompt).run({
            "history": history_str,
            "current_state": state,
            "question": current_question,
            "response": user_input
        })
        
        cleaned_res = clean_json_response(response)
        try:
            new_json = json.loads(cleaned_res)
            if not is_complete_personal_detail(state):
                state["personal_detail"].update(new_json["updated_state"])
            elif state["personal_detail"]["number_of_containers"] >= 3:
                state["more_3"].update(new_json["updated_state"])
            else:
                state["less_3"].update(new_json["updated_state"])
                
            emit('update', {
                'state': state,
                'response': new_json["response"]
            }, room=session_id)
            
            history.append(f"User: {user_input}")
            history.append(f"System: {new_json['response']}")
            
        except json.JSONDecodeError as e:
            emit('error', {'error': f"Failed to parse response: {str(e)}"}, room=session_id)
        
        return state

# ------------------- Main Execution -------------------
if __name__ == '__main__':
    socketio.run(app, host='0.0.0.0', port=5000)