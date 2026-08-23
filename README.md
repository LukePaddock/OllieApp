This is a terminal based ai chat client. It connects to a llama-server instance using the openai python library

If you look in the folder ./old you'll see my original ollama based client, to look at some of the behavior / features I'm looking for.

Please offer some suggestions, or correct me if I'm wrong, but I think it should be setup like follows:

there should be a ollie.py wrapper for the openai library
This could handle the context data, and provide functions to manipulate it.

there should be a storage_handler.py (or similar name) that - in this instance is a repository for prompts, and context (conversations). In theory this could be made into a database - but for now I like my human readable / editable text files as storage. 

I don't want a history of conversations - only context that the user manually saves should be kept.

Text should be streamed (including the <think> parts). The think parts should be part of context (and therefore saved as such when a user saves it).

The client should provide the user ability to quickly swap models, edit model parameters, set the prompt etc