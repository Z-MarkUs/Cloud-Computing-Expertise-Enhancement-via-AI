"""
This module defines the backend API for handling chatbot requests.
It uses Flask and Flask-RESTful to create an API endpoint for generating responses.
"""

import json
from flask import Flask, request, make_response, jsonify
from chat import answer

try:
    from flask_restful import Api  # Import flask_restful with error handling
except ImportError as import_error:
    raise ImportError(
        "Flask-RESTful is not installed. Install it with 'pip install flask-restful'."
    ) from import_error

# Constants should be in UPPER_CASE
APP = Flask(__name__)
API = Api(APP)

@APP.route('/api/ask', methods=['POST'])
def get_prompt_answer():
    """
    Handle POST requests to the '/api/ask' endpoint.
    Processes the user prompt and returns an AI-generated response.
    """
    try:
        data = json.loads(request.data)  # Parse the incoming JSON data
        prompt = data.get("prompt")  # Extract the "prompt" from the request body

        if not prompt:  # Check if the prompt is empty
            return make_response("Empty prompt", 400)

        response, _, _ = answer(prompt)  # Call the `answer` function
        return jsonify({"response": response}), 200

    except json.JSONDecodeError:  # Handle invalid JSON
        return make_response("Invalid JSON format", 400)

    except KeyError as key_error:  # Handle missing keys in data
        return make_response(f"Missing key in request data: {key_error}", 400)

    except (RuntimeError, ValueError) as error:  # Handle other specific exceptions
        print(f"Error occurred: {error}")
        return make_response("AI resources unavailable", 500)


if __name__ == '__main__':
    APP.run(
        host='0.0.0.0', port=5000, debug=True
    )
