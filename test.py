from cryptography.fernet import Fernet  
# Ejecutar una sola vez 
print(Fernet.generate_key().decode())