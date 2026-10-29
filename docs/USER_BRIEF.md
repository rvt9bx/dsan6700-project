# User Brief

### Who is the user? 

The primary target consists of a group of people, whether that's friends, coworkers, family, acquaintances, or even strangers, looking for a movie recommendation and the secondary target is individuals who don't know exactly what they're in the mood for. They might know the general feeling they want but can't land on a specific film. Our app will give each person an equal say in group settings and ease a lot of personal stress in individual ones.

### Where should the user go?

**Application:** [Open the application](http://149.165.147.123:8080/)  
**Project README:** [README.md](../README.md)

### How should the user get started? 

Choose either the individual or group option, then describe in natural language what you feel like watching. For example, you might ask for a thoughtful children's movie containing valuable life lessons about destiny, open-mindedness, perserverance, and love (ie. Disney's 1994 *The Lion King*). 

Try requests you might genuinely use when choosing a movie. Look at whether the recommendations fit your description, and note anything that seems confusing, inaccurate, or difficult to use.

### What can your skeleton do and what can it not do? 

The current application can accept individual requests, create vector embeddings from them, search an IMDb movie database, and return a ranked list of recommendations. Group recommendations are still being refined, particularly how the system balances the preferences of multiple people.

The application may not reliably understand negation. For example, a request for “movies that aren’t scary” could still return a horror film. Displaying details for a selected recommendation other than the top pick also needs improvement. Logging and security features have not yet been implemented.

### What feedback are you seeking?

Please share your thoughts on:

- How easy the application is to understand and use
- Whether you would actually use it to choose a movie and why or why not
- Which additional features would be useful
- Any problems you encounter, including slow response times or recommendations that don’t match your request