from app import app

with app.test_client() as c:
    with c.session_transaction() as sess:
        sess['user_id'] = 1
        sess['role'] = 'admin'
        sess['name'] = 'Admin User'
    
    try:
        response = c.get('/admin/alerts')
        print("STATUS:", response.status_code)
        if response.status_code == 500:
            print("ERROR 500 RECEIVED")
            # Flask test client catches 500 and returns the error page, but we can see the traceback in stderr usually.
            print(response.data.decode('utf-8'))
    except Exception as e:
        import traceback
        traceback.print_exc()
