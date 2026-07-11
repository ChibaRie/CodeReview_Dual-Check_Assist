// Java 静态规则测试 — DAO 层（SQL 注入 + 资源泄漏）
// 基于 Exp8 校园管理系统真实代码

package model;

import org.hibernate.Session;
import org.hibernate.query.Query;
import java.util.List;
import java.util.ArrayList;

public class UserDao {

    // BUG: 资源泄漏 — openSession() 无 close()
    // BUG: SQL 注入 — 字符串拼接 HQL
    public User findBydept(String deptName) {
        Session session = HibernateUtil.getSessionFactory().openSession();
        String hql = "FROM User WHERE dept = '" + deptName + "'";
        Query<User> query = session.createQuery(hql);
        List<User> results = query.list();
        session.close();  // 这一行有 close — OK
        return results.isEmpty() ? null : results.get(0);
    }

    // BUG: 资源泄漏 — openSession() 后无 close()
    public List<User> findByName(String userName) {
        Session session = HibernateUtil.getSessionFactory().openSession();
        Query<User> query = session.createQuery(hql);
        return query.list();
    }

    // BUG: SQL 注入 — delete 语句字符串拼接
    public void deleteUser(String userId) {
        Session session = HibernateUtil.getSessionFactory().openSession();
        session.createQuery("DELETE FROM User WHERE id = '" + userId + "'").executeUpdate();
        session.close();
    }

    // OK: parameterized query — 参数化查询
    public User findByEmail(String email) {
        Session session = HibernateUtil.getSessionFactory().openSession();
        Object result = session.createQuery("FROM User WHERE email = :email")
                .setParameter("email", email)
                .uniqueResult();
        session.close();
        return (User) result;
    }
}

// Stub
class HibernateUtil {
    static SessionFactory getSessionFactory() { return null; }
}
class SessionFactory { Session openSession() { return null; } }
class User {}
