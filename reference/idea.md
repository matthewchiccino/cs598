# Original idea (Matthew)

My idea was running experiments to test if LLMs can improve or fix their own mistakes without outside feedback (external tool calling) against something specific and concrete. To see if their own feedback is enough.

A good topic and use case I think it's interesting and easy to understand, and also easy to measure, is to draw SVGs of country shapes/borders using its own knowledge, no web or map data. We can create a model answer test suite with existing accurate svg shapes (normalized and everything).

We could compare one shot attempt, agent views and self corrects, and also using its own memory from its own mistakes.

Another interesting layer will be comparing most popular vs niche countries, and seeing how less accurate it can get based on how much it's been familiar with it from model training.
