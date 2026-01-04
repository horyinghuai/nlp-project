function toggleChat() {
    var chat = document.getElementById("chat-widget");
    // This adds/removes the 'active' class, triggering the CSS transition
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
    
    // Auto-scroll to bottom
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