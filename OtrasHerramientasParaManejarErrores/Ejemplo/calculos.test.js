/* global require, describe, test, expect */
// calculos.test.js
const { cobrar } = require('./calculos');

describe("Función de cobros", () => {
    
    // Prueba 1: El camino feliz
    test("Debe aplicar un 10% de descuento correctamente", () => {
        const resultado = cobrar(100, 0.10);
        expect(resultado).toBe(90); // Esperamos que 100 menos 10% sea 90
    });

    // Prueba 2: La validación de errores
    test("Debe lanzar un error si el descuento es mayor al precio", () => {
        // Un descuento del 200% daría un total negativo, debe explotar
        expect(() => cobrar(100, 2.0)).toThrow("El total no puede ser negativo");
    });
});