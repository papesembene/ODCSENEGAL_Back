// backend/server.js
const express = require('express');
const cors = require('cors');
const app = express();
const PORT = 3000; // Choisir un port pour le serveur backend

// Middleware
app.use(cors()); // Permet à ton frontend Next.js d'accéder à ton API
app.use(express.json()); // Permet de parser les requêtes JSON

// Routes
app.post('/api/auth/login', (req, res) => {
  const { email, password } = req.body;

  // Logic de connexion ici (vérification des identifiants, génération de token JWT, etc.)
  if (email === 'test@example.com' && password === 'password') {
    res.json({ access_token: 'fake_token', user: { name: 'Test User' } });
  } else {
    res.status(401).json({ error: 'Invalid credentials' });
  }
});

// Autres routes pour ton API
// app.use('/api/other-routes', otherRoutes);

// Démarrer le serveur
app.listen(PORT, () => {
  console.log(`Backend is running on http://localhost:${PORT}`);
});
