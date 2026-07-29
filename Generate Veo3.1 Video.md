Generate Veo3.1 Video

**cURL**

Request

curl --location --request POST 'https://api.kie.ai/api/v1/veo/generate' \\

\--header 'Authorization: Bearer <token>' \\

\--header 'Content-Type: application/json' \\

\--data-raw '{

&#x20; "prompt": "A dog playing in a park",

&#x20; "imageUrls": \[

&#x20;   "http://example.com/image1.jpg",

&#x20;   "http://example.com/image2.jpg"

&#x20; ],

&#x20; "model": "veo3\_fast",

&#x20; "watermark": "MyBrand",

&#x20; "callBackUrl": "http://your-callback-url.com/complete",

&#x20; "aspect\_ratio": "16:9",

&#x20; "seeds": 12345,

&#x20; "enableFallback": false,

&#x20; "enableTranslation": true,

&#x20; "generationType": "REFERENCE\_2\_VIDEO"

}'



&#x20;Response

{

&#x20;   "code": 500,

&#x20;   "msg": "Server Error - An unexpected error occurred while processing the request",

&#x20;   "data": null

}



**cURL-Windows**



Request 



curl --location --request POST "https://api.kie.ai/api/v1/veo/generate" ^

\--header "Authorization: Bearer <token>" ^

\--header "Content-Type: application/json" ^

\--data-raw "{  \\"prompt\\": \\"A dog playing in a park\\",  \\"imageUrls\\": \[    \\"http://example.com/image1.jpg\\",    \\"http://example.com/image2.jpg\\"  ],  \\"model\\": \\"veo3\_fast\\",  \\"watermark\\": \\"MyBrand\\",  \\"callBackUrl\\": \\"http://your-callback-url.com/complete\\",  \\"aspect\_ratio\\": \\"16:9\\",  \\"seeds\\": 12345,  \\"enableFallback\\": false,  \\"enableTranslation\\": true,  \\"generationType\\": \\"REFERENCE\_2\_VIDEO\\"}"



Response

{

&#x20;   "code": 500,

&#x20;   "msg": "Server Error - An unexpected error occurred while processing the request",

&#x20;   "data": null

}



**PowerShell**



Request

$headers = New-Object "System.Collections.Generic.Dictionary\[\[String],\[String]]"

$headers.Add("Authorization", "Bearer <token>")

$headers.Add("Content-Type", "application/json")



$body = "{`n  `"prompt`": `"A dog playing in a park`",`n  `"imageUrls`": \[`n    `"http://example.com/image1.jpg`",`n    `"http://example.com/image2.jpg`"`n  ],`n  `"model`": `"veo3\_fast`",`n  `"watermark`": `"MyBrand`",`n  `"callBackUrl`": `"http://your-callback-url.com/complete`",`n  `"aspect\_ratio`": `"16:9`",`n  `"seeds`": 12345,`n  `"enableFallback`": false,`n  `"enableTranslation`": true,`n  `"generationType`": `"REFERENCE\_2\_VIDEO`"`n}"



$response = Invoke-RestMethod 'https://api.kie.ai/api/v1/veo/generate' -Method 'POST' -Headers $headers -Body $body

$response | ConvertTo-Json



Response

{

&#x20;   "code": 500,

&#x20;   "msg": "Server Error - An unexpected error occurred while processing the request",

&#x20;   "data": null

}











