# Xcrover Admin Web Panel

Flask tabanlı Xcrover admin paneli.

## Render Deployment

### Environment Variables
Render Dashboard → Environment sekmesinde şu değişkenleri ekleyin:

```
MONGODB_URI=mongodb+srv://mustafaylmaz3566_db_user:mustafa65@cluster0.x4l2qe7.mongodb.net/xcrover
SECRET_KEY=your-random-secret-key-minimum-32-characters
USE_MONGODB_DRIVER=true
```

### Deploy Steps

1. Git repository'nizi Render'a bağlayın
2. Environment variables'ları ekleyin (yukarıdaki gibi)
3. Build & Deploy

### Local Development

```bash
# Install dependencies
pip install -r requirements.txt

# Create .env file
cp .env.example .env
# Edit .env with your MongoDB credentials

# Run
python app.py
```

## Features

- License Management
- Premium Games
- Denuvo Games
- Manual Games (ZIP upload)
- Bypass Packages
- Announcements
- Updates
- Support Tickets
- Resellers
- Dashboard

## Login

Username: `admin`
Password: `admin123`
