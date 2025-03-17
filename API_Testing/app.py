import re
from typing import Optional, TypedDict, List
from langgraph.graph import StateGraph, START, END
from langchain.chains import LLMChain
from langchain.prompts import PromptTemplate
from langchain_openai import ChatOpenAI
import dotenv
import json
import asyncio
import socketio
import uvicorn


dotenv.load_dotenv()

message_event = asyncio.Event()

def clean_json_response(response: str) -> str:
    # Extract JSON between ```json ... ```
    match = re.search(r"```json(.*?)```", response.strip(), re.DOTALL)
    return match.group(1).strip()

class ShippingWorkflowState(TypedDict):
    personal_detail: Optional[dict]  
    more_3: Optional[dict] 
    less_3: Optional[dict] 


# --- Chat History Store ---
# A global dictionary to store chat history per session.
store = {}
session_id = "foo"
message_from_client = ""

def get_by_session_id(session_id: str) -> List[str]:
    if session_id not in store:
        store[session_id] = []
    return store[session_id]

# For this example, we use a fixed session id.


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
    required_fields = ["number_of_containers",
    "used_service_before",
    "size",
    "empty_or_loaded",
    "hazardous",
    "new_customer",
    "corner_casting",
    "protrusions_end_or_top",
    "protrusions_long_side",
    "pickup_address",
    "lifting_setup",
    "container_door_opening_pickup",
    "pickup_surface_type",
    "pickup_location_grade",
    "delivery_address",
    "dropping_setup",
    "container_door_opening_drop_off",
    "drop_off_surface_type",
    "drop_off_location_grade"]
    
    # Check if all required fields are present
    if not all(state["less_3"].get(field) for field in required_fields):
        return False
    
    # Check if all elements in the lists are present
    for field in ["number_of_containers",
    "used_service_before",
    "size",
    "empty_or_loaded",
    "hazardous",
    "new_customer",
    "corner_casting",
    "protrusions_end_or_top",
    "protrusions_long_side",
    "pickup_address",
    "lifting_setup",
    "container_door_opening_pickup",
    "pickup_surface_type",
    "pickup_location_grade",
    "delivery_address",
    "dropping_setup",
    "container_door_opening_drop_off",
    "drop_off_surface_type",
    "drop_off_location_grade"]:
        if any(not item for item in state["less_3"].get(field, [])):
            return False
    
    return True

# Initialize the LLM.
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


# Global variable to hold the current question.
current_question = None

# --- Node Functions ---

async def ask_question_node(state: ShippingWorkflowState) -> ShippingWorkflowState:
    if is_complete_personal_detail(state):
        return state

    # Retrieve session history and format as string.
    history = get_by_session_id(session_id)
    history_str = "\n".join(history)
    
    # Format the prompt with the current state and chat history.
    formatted_prompt = question_prompt_personal_detail.format(history=history_str, current_state=state["personal_detail"])
    
    # Call the LLM to generate a question.
    response = LLMChain(llm=llm, prompt=question_prompt_personal_detail).run({
        "history": history_str,
        "current_state": state["personal_detail"]
    })
    
    global current_question
    current_question = response
    
    # Append the question to the chat history.
    history.append("\nQuestion asked: " + response)
    return state

async def process_answer_node(state: ShippingWorkflowState) -> ShippingWorkflowState:
    history = get_by_session_id(session_id)
    history_str = "\n".join(history)
    
    await reply_to_client("Question from Chatbot: "+current_question)
    # Ask the user for their input in response to the current question.
    global message_from_client
    await message_event.wait()  # this yields control back to the event loop
    user_input = message_from_client
    message_event.clear()
    message_from_client = ""
    
    
    # Format the state update prompt.
    formatted_prompt = state_update_prompt_personal_detail.format(
        history=history_str, current_state=state["personal_detail"],
        question=current_question, response=user_input
    )
    
    # Call the LLM to update the state.
    response = LLMChain(llm=llm, prompt=state_update_prompt_personal_detail).run({
        "history": history_str,
        "current_state": state["personal_detail"],
        "question": current_question,
        "response": user_input
    })
    
    cleaned_res = clean_json_response(response)
    try:
        new_json = json.loads(cleaned_res)
        new_state = new_json["updated_state"]
        # clear the ouput before printing
        # print("\nResponse from Chatbot: ", new_json["response"])
        await reply_to_client("Response from Chatbot on the answer: "+new_json["response"])
        
        
        
        state["personal_detail"].update(new_state)
        
        print("cuurent state: ", state)
        await state_json(state)
        
        # print("\nUpdated State: ", state)
        if state["personal_detail"]["number_of_containers"] != None:
            state["more_3"]["number_of_containers"] = state["personal_detail"]["number_of_containers"]
            state["less_3"]["number_of_containers"] = state["personal_detail"]["number_of_containers"]
    except json.JSONDecodeError as e:
        print("Error decoding JSON:", e)
        print("Response:", cleaned_res)
    
    # Append the update to the chat history.
    history.append("User Input: "+user_input+"Response from Chatbot: "+new_json["response"]+"\nUpdated State: " + cleaned_res)
    return state

async def more_than_3_ask_node(state: ShippingWorkflowState) -> ShippingWorkflowState:
    if is_complete_more3(state):
        return state

    # Retrieve session history and format as string.
    history = get_by_session_id(session_id)
    history_str = "\n".join(history)
    
    # Format the prompt with the current state and chat history.
    formatted_prompt = question_prompt_more3.format(history=history_str, current_state=state["more_3"])
    
    # Call the LLM to generate a question.
    response = LLMChain(llm=llm, prompt=question_prompt_more3).run({
        "history": history_str,
        "current_state": state["more_3"]
    })
    
    global current_question
    current_question = response
    
    # Append the question to the chat history.
    history.append("\nQuestion asked: " + response)
    return state

async def more_than_3_process_node(state: ShippingWorkflowState) -> ShippingWorkflowState:
    history = get_by_session_id(session_id)
    history_str = "\n".join(history)
    
    
    await reply_to_client("Question from Chatbot: "+current_question)
    # Ask the user for their input in response to the current question.
    global message_from_client
    await message_event.wait()  # this yields control back to the event loop
    user_input = message_from_client
    message_event.clear()
    message_from_client = ""
    
    
    # Format the state update prompt.
    formatted_prompt = state_update_prompt_more3.format(
        history=history_str, current_state=state["more_3"],
        question=current_question, response=user_input
    )
    
    # Call the LLM to update the state.
    response = LLMChain(llm=llm, prompt=state_update_prompt_more3).run({
        "history": history_str,
        "current_state": state["more_3"],
        "question": current_question,
        "response": user_input
    })
    
    cleaned_res = clean_json_response(response)
    try:
        new_json = json.loads(cleaned_res)
        new_state = new_json["updated_state"]
        # clear the ouput before printing
        # print("\nResponse from Chatbot: ", new_json["response"])
        
        await reply_to_client("Response from Chatbot on the answer: "+new_json["response"])
        
        # keys_to_exclude = {'empty_or_loaded', 'pickup_address', 'delivery_address'}
        # state.update({k: v for k, v in new_state.items() if k not in keys_to_exclude})
        state["more_3"].update(new_state)
        
        await state_json(state)
        
        print("\nUpdated State: ", state)
    except json.JSONDecodeError as e:
        print("Error decoding JSON:", e)
        print("Response:", cleaned_res)
    
    # Append the update to the chat history.
    history.append("User Input: "+user_input+"Response from Chatbot: "+new_json["response"]+"\nUpdated State: " + cleaned_res)
    return state

async def less_than_3_ask_node(state: ShippingWorkflowState) -> ShippingWorkflowState:
    if is_complete_less3(state):
        return state

    # Retrieve session history and format as string.
    history = get_by_session_id(session_id)
    history_str = "\n".join(history)
    
    # Format the prompt with the current state and chat history.
    formatted_prompt = question_prompt_less3.format(history=history_str, current_state=state["less_3"])
    
    # Call the LLM to generate a question.
    response = LLMChain(llm=llm, prompt=question_prompt_less3).run({
        "history": history_str,
        "current_state": state["less_3"]
    })
    
    global current_question
    current_question = response
    
    # Append the question to the chat history.
    history.append("\nQuestion asked: " + response)
    return state

async def less_than_3_process_node(state: ShippingWorkflowState) -> ShippingWorkflowState:
    history = get_by_session_id(session_id)
    history_str = "\n".join(history)
    
    await reply_to_client("Question from Chatbot: "+current_question)
    # Ask the user for their input in response to the current question.
    global message_from_client
    await message_event.wait()  # this yields control back to the event loop
    user_input = message_from_client
    message_event.clear()
    message_from_client = ""
    
    # Format the state update prompt.
    formatted_prompt = state_update_prompt_less3.format(
        history=history_str, current_state=state["less_3"],
        question=current_question, response=user_input
    )
    
    # Call the LLM to update the state.
    response = LLMChain(llm=llm, prompt=state_update_prompt_less3).run({
        "history": history_str,
        "current_state": state["less_3"],
        "question": current_question,
        "response": user_input
    })
    
    cleaned_res = clean_json_response(response)
    try:
        new_json = json.loads(cleaned_res)
        new_state = new_json["updated_state"]
        # clear the ouput before printing
        # print("\nResponse from Chatbot: ", new_json["response"])
        
        await reply_to_client("Response from Chatbot on the answer: "+new_json["response"])
        
        # keys_to_exclude = {'empty_or_loaded', 'pickup_address', 'delivery_address'}
        # state.update({k: v for k, v in new_state.items() if k not in keys_to_exclude})
        state["less_3"].update(new_state)
        
        await state_json(state)
        
        print("\nUpdated State: ", state)
    except json.JSONDecodeError as e:
        print("Error decoding JSON:", e)
        print("Response:", cleaned_res)
    
    # Append the update to the chat history.
    history.append("User Input: "+user_input+"Response from Chatbot: "+new_json["response"]+"\nUpdated State: " + cleaned_res)
    return state

def workflow_complete_node(state: ShippingWorkflowState) -> ShippingWorkflowState:
    print("Workflow completed.")
    print("Final state:", state)
    return state

# --- Conditional Routing Functions ---
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


# --- Build the LangGraph State Graph ---
workflow = StateGraph(ShippingWorkflowState)
workflow.add_node("ask_question", ask_question_node)
workflow.add_node("process_answer", process_answer_node)
workflow.add_node("more_than_3_ask", more_than_3_ask_node)
workflow.add_node("more_than_3_process", more_than_3_process_node)
workflow.add_node("less_than_3_ask", less_than_3_ask_node)
workflow.add_node("less_than_3_process", less_than_3_process_node)

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

app_graph = workflow.compile()


personal_detail: Optional[dict] = {
"full_name": None,
"company_name": None,
"company_address": None,
"phone_number": None,
"email": None,
"number_of_containers": None
}

more_3: Optional[dict] = {
    "number_of_containers": None,
    "size": None,  # Size of the containers
    "empty_or_loaded": None,  # List of container statuses
    "pickup_address": None,   # Pickup addresses for the containers
    "delivery_address": None  # Delivery addresses for the containers
}

less_3: Optional[dict] = {
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


    # The final state will now have these steps as part of it.
state: ShippingWorkflowState = {
    "personal_detail": personal_detail,
    "more_3": more_3,
    "less_3": less_3
}

# sio = socketio.AsyncServer(async_mode='asgi')
sio = socketio.AsyncServer(
    async_mode='asgi',
    cors_allowed_origins="*"
)

app = socketio.ASGIApp(sio, static_files={
    '/': 'main_test.html',
})



@sio.event
async def connect(sid, environ):
    print('connect ', sid)
    await sio.emit('sid', sid, room=sid)
    
@sio.event
async def disconnect(sid):
    print('disconnect ', sid)



@sio.event
async def message(sid, data):
    print('Message received from client:', data)
    global message_from_client
    message_from_client = data
    # await reply_to_client(data)
    # await sio.emit('reply', f"Server received: {data}", room=sid)
    message_event.set()

@sio.event
async def start_workflow(sid):
    print('Starting workflow')
    session_id = sid
    global state
    await app_graph.ainvoke(state,{"recursion_limit": 100})
    print("Final state:", state)
    

async def reply_to_client(message):
    await sio.emit('reply', message)

async def state_json(message):
    await sio.emit('state_json', message)


if __name__ == '__main__':
    
    uvicorn.run(app)
    
