
FLOW: [Mic] → Capture → Segmenter (VAD) → Transcriber (Whisper) → Structurer (LLM) → UI

Create an application with a Python graphical user interface (PySide6 (Qt)) that will capture voice from the user and transcribe it to text using
 Transcription: openai-whisper easy model swap (small/medium/large). Expose model picker in settings.
Then, in real time, while receiving the text and transcribing it, pack this text into the structure. The text could be, for example, the speech from the doctor containing:
- the diagnosis of the patient
- the proposed treatment
- the name of the patient or year of birth
- any other relevant information
This structures should be defined by the contract given in the config.json file. Try firstly with a small Whispr model, but also allow the user to select the larger Whispr model depending on the possibilities of the computer this is executed on.
The user should see on the left part of the app window the text being transcribed, and on the right part it should see this form read from the config.json containing a grouping, assigning transcribed text into each of these fields - in the real time, as transcribed text is coming from the user. This filling, the conversion of this raw text dictated from the user to this structured form, should also be performed with free AI models from OpenRouter (API key will be provided as environment variable in .env file, use these models in the order best for this problem first: google/gemini-2.0-flash-exp:free, meta-llama/llama-3.3-70b-instruct:free,
   deepseek/deepseek-chat-v3:free), so propose the architecture convenient for this task.
The user press "Talk" button (that changes name to Stop) and model listens and transcribes until the user presses "Stop" button (Changes back to Talk). English and Serbian languages should be supported. Shen user presses Stop the transcribed text and structured text should be saved to output JSON containing current date and time in file name.
Toold should be able to run on MacOS, Linux, and Windows.

config.json:
{"key": "patient_name", "label": "Name", "type": "string"},
{"key": "year_of_birth", "label": "YOB", "type": "integer"}
{"key": "diagnosis", "label": "Diagnosis", "type": "string"},
{"key": "treatment", "label": "Proposed treatment", "type": "string"}
Add logging of the execution steps, create easy to understand and well-commented code. Create main in main.py file and rest of the needed python files put in source folder.