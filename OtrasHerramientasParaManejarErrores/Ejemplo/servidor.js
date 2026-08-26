// servidor.js
const express = require('express');
const Sentry = require('@sentry/node');
const { cobrar } = require('./calculos');

const app = express();

// Iniciamos Sentry
Sentry.init({ dsn: "CLAVE-SENTRY" });


app.get('/procesar-pago', (req, res) => {
    // Un descuento del 200% dará un total de -100, lo que lanzará nuestro Error
    const precio = 100; 
    const descuento = 2.0;

    const total = cobrar(precio, descuento); 
    res.send(`Total a pagar: ${total}`);
});

Sentry.setupExpressErrorHandler(app);

app.listen(3000, () => console.log("Servidor corriendo"));