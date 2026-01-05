// Chatbot Logic
function toggleChat() {
    var chat = document.getElementById("chat-widget");
    chat.classList.toggle("active");
}

function handleEnter(event) {
    if (event.key === "Enter") sendMessage();
}

function sendMessage() {
    var input = document.getElementById("chat-input");
    var message = input.value.trim();
    if (!message) return;

    var chatBody = document.getElementById("chat-body");
    chatBody.innerHTML += `<div class="user-msg">${message}</div>`;
    input.value = "";
    
    chatBody.scrollTop = chatBody.scrollHeight;

    fetch('/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message: message })
    })
    .then(response => response.json())
    .then(data => {
        chatBody.innerHTML += `<div class="bot-msg">${data.reply}</div>`;
        chatBody.scrollTop = chatBody.scrollHeight;
    });
}

// File Upload Logic (New)
function handleFileSelect(input) {
    if (input.files && input.files[0]) {
        var file = input.files[0];
        
        // Update file name in display
        document.getElementById('file-name').textContent = file.name;
        
        // Hide upload label, show display
        document.getElementById('upload-label').style.display = 'none';
        document.getElementById('file-display').style.display = 'flex';
    }
}

function removeFile() {
    var input = document.getElementById('file-upload');
    input.value = ""; // Clear the input
    
    // Hide display, show upload label
    document.getElementById('file-display').style.display = 'none';
    document.getElementById('upload-label').style.display = 'block';
}