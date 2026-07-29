**Nano Banana Pro Api documentation**

**POST**

**/api/v1/jobs/createTask**

**Image generation using Google's Pro Image to Image model**

**Query Task Status**

**After submitting a task, use the unified query endpoint to check progress and retrieve results:**

**Get Task Details**

**Learn how to query task status and retrieve generation results**

**For production use, we recommend using the callBackUrl parameter to receive automatic notifications when generation completes, rather than polling the status endpoint.**

**Related Resources**

**Market Overview**

**Explore all available models**

**Common API**

**Check credits and account usage**

**Request**

**Authorization**

**Bearer Token**

**Provide your bearer token in the Authorization header when making requests to protected resources.**

**Example:**

**Authorization: Bearer \*\*\*\*\*\*\*\*\*\*\*\*\*\*\*\*\*\*\*\***

**Body Params**

**application/json**

**Required**

**model**

**enum<string>** 

**required**

**The model name to use for generation. Required field.**

**Must be nano-banana-pro for this endpoint**

**Value:**

**nano-banana-pro**

**Default:**

**nano-banana-pro**

**Example:**

**nano-banana-pro**

**callBackUrl**

**string <uri>**

**optional**

**The URL to receive generation task completion updates. Optional but recommended for production use.**

**System will POST task status and results to this URL when generation completes**

**Callback includes generated content URLs and task information**

**Your callback endpoint should accept POST requests with JSON payload containing results**

**Alternatively, use the Get Task Details endpoint to poll task status**

**To ensure callback security, see Webhook Verification Guide for signature verification implementation**

**Example:**

**https://your-domain.com/api/callback**

**input**

**object** 

**optional**

**Input parameters for the generation task**

**prompt**

**string** 

**required**

**A text description of the image you want to generate (Max length: 10000 characters)**

**<= 10000 characters**

**Example:**

**Comic poster: cool banana hero in shades leaps from sci-fi pad. Six panels: 1) 4K mountain landscape, 2) banana holds page of long multilingual text with auto translation, 3) Gemini 3 hologram for search/knowledge/reasoning, 4) camera UI sliders for angle focus color, 5) frame trio 1:1-9:16, 6) consistent banana poses. Footer shows Google icons. Tagline: Nano Banana Pro now on Kie AI.**

**image\_input**

**array\[string <uri>]**

**optional**

**Input images to transform or use as reference (supports up to 8 images) (File URL after upload, not file content; Accepted types: image/jpeg, image/png, image/webp; Max size: 30.0MB)**

**<= 8 items**

**Example:**

**\[]**

**aspect\_ratio**

**enum<string>** 

**optional**

**Aspect ratio of the generated image**

**Allowed values:**

**1:1**

**2:3**

**3:2**

**3:4**

**4:3**

**4:5**

**5:4**

**9:16**

**16:9**

**21:9**

**auto**

**Default:**

**1:1**

**Example:**

**1:1**

**resolution**

**enum<string>** 

**optional**

**Resolution of the generated image**

**Allowed values:**

**1K**

**2K**

**4K**

**Default:**

**1K**

**Example:**

**1K**

**output\_format**

**enum<string>** 

**optional**

**Format of the output image**

**Allowed values:**

**png**

**jpg**

**Default:**

**png**

**Example:**

**png**

**Examples**

**Responses**

**🟢200**

**application/json**

**Request successful**

**Body**

**code**

**enum<integer>** 

**optional**

**Response status code**

**200: Success - Request has been processed successfully**

**401: Unauthorized - Authentication credentials are missing or invalid**

**402: Insufficient Credits - Account does not have enough credits to perform the operation**

**404: Not Found - The requested resource or endpoint does not exist**

**422: Validation Error - The request parameters failed validation checks**

**429: Rate Limited - Request limit has been exceeded for this resource**

**455: Service Unavailable - System is currently undergoing maintenance**

**500: Server Error - An unexpected error occurred while processing the request**

**501: Generation Failed - Content generation task failed**

**505: Feature Disabled - The requested feature is currently disabled**

**Allowed values:**

**200**

**401**

**402**

**404**

**422**

**429**

**455**

**500**

**501**

**505**

**msg**

**string** 

**optional**

**Response message, error description when failed**

**Example:**

**success**

**data**

**object** 

**required**

**taskId**

**string** 

**required**

**Task ID, can be used with Get Task Details endpoint to query task status**

**🔴500**

**Error**

















































**nanobanana curl**

Request

curl --location --request POST 'https://api.kie.ai/api/v1/jobs/createTask' \\

\--header 'Authorization: Bearer <token>' \\

\--header 'Content-Type: application/json' \\

\--data-raw '{

&#x20;   "model": "nano-banana-pro",

&#x20;   "callBackUrl": "https://your-domain.com/api/callback",

&#x20;   "input": {

&#x20;       "prompt": "Comic poster: cool banana hero in shades leaps from sci-fi pad. Six panels: 1) 4K mountain landscape, 2) banana holds page of long multilingual text with auto translation, 3) Gemini 3 hologram for search/knowledge/reasoning, 4) camera UI sliders for angle focus color, 5) frame trio 1:1-9:16, 6) consistent banana poses. Footer shows Google icons. Tagline: Nano Banana Pro now on Kie AI.",

&#x20;       "image\_input": \[],

&#x20;       "aspect\_ratio": "1:1",

&#x20;       "resolution": "1K",

&#x20;       "output\_format": "png"

&#x20;   }

}'



Response

{

&#x20;   "code": 200,

&#x20;   "msg": "success",

&#x20;   "data": {

&#x20;       "taskId": "task\_nano-banana-pro\_1765178625768"

&#x20;   }

}



**Nanobanana cURL-Windows**



Request 



curl --location --request POST "https://api.kie.ai/api/v1/jobs/createTask" ^

\--header "Authorization: Bearer <token>" ^

\--header "Content-Type: application/json" ^

\--data-raw "{    \\"model\\": \\"nano-banana-pro\\",    \\"callBackUrl\\": \\"https://your-domain.com/api/callback\\",    \\"input\\": {        \\"prompt\\": \\"Comic poster: cool banana hero in shades leaps from sci-fi pad. Six panels: 1) 4K mountain landscape, 2) banana holds page of long multilingual text with auto translation, 3) Gemini 3 hologram for search/knowledge/reasoning, 4) camera UI sliders for angle focus color, 5) frame trio 1:1-9:16, 6) consistent banana poses. Footer shows Google icons. Tagline: Nano Banana Pro now on Kie AI.\\",        \\"image\_input\\": \[],        \\"aspect\_ratio\\": \\"1:1\\",        \\"resolution\\": \\"1K\\",        \\"output\_format\\": \\"png\\"    }}"



Response



{

&#x20;   "code": 200,

&#x20;   "msg": "success",

&#x20;   "data": {

&#x20;       "taskId": "task\_nano-banana-pro\_1765178625768"

&#x20;   }

}



**PowerShell**



Request

$headers = New-Object "System.Collections.Generic.Dictionary\[\[String],\[String]]"

$headers.Add("Authorization", "Bearer <token>")

$headers.Add("Content-Type", "application/json")



$body = "{`n    `"model`": `"nano-banana-pro`",`n    `"callBackUrl`": `"https://your-domain.com/api/callback`",`n    `"input`": {`n        `"prompt`": `"Comic poster: cool banana hero in shades leaps from sci-fi pad. Six panels: 1) 4K mountain landscape, 2) banana holds page of long multilingual text with auto translation, 3) Gemini 3 hologram for search/knowledge/reasoning, 4) camera UI sliders for angle focus color, 5) frame trio 1:1-9:16, 6) consistent banana poses. Footer shows Google icons. Tagline: Nano Banana Pro now on Kie AI.`",`n        `"image\_input`": \[],`n        `"aspect\_ratio`": `"1:1`",`n        `"resolution`": `"1K`",`n        `"output\_format`": `"png`"`n    }`n}"



$response = Invoke-RestMethod 'https://api.kie.ai/api/v1/jobs/createTask' -Method 'POST' -Headers $headers -Body $body

$response | ConvertTo-Json





Response



{

&#x20;   "code": 200,

&#x20;   "msg": "success",

&#x20;   "data": {

&#x20;       "taskId": "task\_nano-banana-pro\_1765178625768"

&#x20;   }

}

