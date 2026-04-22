from PIL import Image

# Example: Open and display image information
def main():
    print("Pillow library successfully imported!")
    print(f"Pillow version: {Image.__module__}")
    
    # Example: Create a simple image
    img = Image.new('RGB', (100, 100), color='red')
    print(f"Created a {img.size[0]}x{img.size[1]} red image")
    
    # Save the image
    img.save('test_image.png')
    print("Image saved as 'test_image.png'")

if __name__ == "__main__":
    main()
