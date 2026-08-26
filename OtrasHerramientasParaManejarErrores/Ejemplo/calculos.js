// calculos.js
function cobrar(precio, descuento) {
    const total = precio - (precio * descuento);
    
    // Variable mal escrita ('totl' en vez de 'total')
    if (total < 0) {
        throw new Error("El total no puede ser negativo");
    }
    return total;
}

module.exports = { cobrar };