// JavaScript 静态规则测试 — var / == / console.log / 回调嵌套
// 基于常见前端代码审查问题

// BUG: var 声明 — 应用 let/const
var userName = "admin";

// BUG: == 代替 ===
function isAdmin(role) {
    if (role == "admin") {
        return true;
    }
    return false;
}

// BUG: console.log 调试残留
function fetchUserData(userId) {
    console.log("fetching user:", userId);
    return fetch("/api/users/" + userId)
        .then(response => response.json())
        .then(data => {
            console.log("got data:", data);
            return data;
        });
}

// BUG: console.debug 调试残留
function debugMode() {
    console.debug("debug mode active");
    console.warn("this should use a proper logger");
}

// OK: 使用 const 和 ===
const API_URL = "https://api.example.com";
function isAdminSafe(role) {
    return role === "admin";
}

// OK: 使用 let
let counter = 0;
function increment() {
    counter += 1;
    return counter;
}
