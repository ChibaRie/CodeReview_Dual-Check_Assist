// Java 静态规则测试 — 模型/控制器层（硬编码密码 + 调试残留 + 原始类型）
// 基于 Exp8 校园管理系统真实代码

package controller;

import java.util.List;
import java.util.ArrayList;
import java.util.HashMap;
import model.User;

public class UserOperationController {

    // BUG: 硬编码密码
    private static final String ADMIN_PASSWORD = "admin123";

    // BUG: 调试残留
    public void listUsers() {
        List users = new ArrayList();  // BUG: 原始类型
        users.add(new User());
        System.out.println("Total users: " + users.size());
    }

    // BUG: 调试残留 + 原始类型
    public void processDept() {
        Map deptMap = new HashMap();  // BUG: 原始类型
        try {
            deptMap.put("IT", loadDept("IT"));
        } catch (Exception e) {
            e.printStackTrace();  // BUG: 调试残留
        }
    }

    // OK: 正确泛型
    public List<User> findActiveUsers() {
        List<User> activeUsers = new ArrayList<>();
        return activeUsers;
    }

    // BUG: 未使用的 import（本文件 import HashMap 但此处用不上）
    private Object loadDept(String name) {
        return null;
    }
}

class User {}
