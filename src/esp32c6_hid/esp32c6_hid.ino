// This firmware is for the Seeed Studio XIAO ESP32-S3.
// It uses BLE to receive commands and acts as a USB HID keyboard and mouse.

#include <Arduino.h>
#include <BLEDevice.h>
#include <BLEServer.h>
#include <BLEUtils.h>
#include <BLE2902.h>
#include <USB.h>
#include <USBHIDKeyboard.h>
#include <USBHIDMouse.h>

// UUIDs for our BLE service and characteristic
#define SERVICE_UUID        "c48e6067-5295-48d3-8d5c-0395f61792b1"
#define CHARACTERISTIC_UUID "c48e6068-5295-48d3-8d5c-0395f61792b1"

// Onboard LED pin for Seeed Studio XIAO ESP32-S3.
// The board package should define LED_BUILTIN.
// Typically, this is the blue LED on GPIO 21.

// Global variables
USBHIDKeyboard keyboard;
USBHIDMouse mouse;
bool deviceConnected = false;
unsigned long lastLedToggle = 0;
bool ledState = false;

// Server callbacks to handle connection and disconnection
class MyServerCallbacks: public BLEServerCallbacks {
    void onConnect(BLEServer* pServer) {
      deviceConnected = true;
      Serial.println("Device connected");
    }

    void onDisconnect(BLEServer* pServer) {
      deviceConnected = false;
      Serial.println("Device disconnected");
      digitalWrite(LED_BUILTIN, LOW); // Turn LED off on disconnect
      // Restart advertising to allow new connections
      pServer->getAdvertising()->start();
      Serial.println("Restarting advertising");
    }
};

// Characteristic callbacks to handle incoming data
class MyCharacteristicCallbacks: public BLECharacteristicCallbacks {
    void onWrite(BLECharacteristic *pCharacteristic) {
      String value = pCharacteristic->getValue();

      if (value.length() > 0) {
        Serial.print("Received Value: ");
        Serial.println(value);

        // Command parsing logic
        if (value.startsWith("k:")) {
          String toType = value.substring(2);
          keyboard.print(toType);
          Serial.print("Typing: ");
          Serial.println(toType);
        } else if (value.startsWith("m:")) {
          String coords = value.substring(2);
          int commaIndex = coords.indexOf(',');
          if (commaIndex != -1) {
            int x = coords.substring(0, commaIndex).toInt();
            int y = coords.substring(commaIndex + 1).toInt();
            mouse.move(x, y);
            Serial.print("Moving mouse: ");
            Serial.print(x);
            Serial.print(",");
            Serial.println(y);
          }
        } else if (value.startsWith("mc:")) {
          String button = value.substring(3);
          if (button == "left") {
            mouse.click(MOUSE_LEFT);
            Serial.println("Mouse left click");
          } else if (button == "right") {
            mouse.click(MOUSE_RIGHT);
            Serial.println("Mouse right click");
          } else if (button == "middle") {
            mouse.click(MOUSE_MIDDLE);
            Serial.println("Mouse middle click");
          }
        } else if (value.startsWith("mp:")) {
          String button = value.substring(3);
          if (button == "left") {
            mouse.press(MOUSE_LEFT);
            Serial.println("Mouse left press");
          } else if (button == "right") {
            mouse.press(MOUSE_RIGHT);
            Serial.println("Mouse right press");
          } else if (button == "middle") {
            mouse.press(MOUSE_MIDDLE);
            Serial.println("Mouse middle press");
          }
        } else if (value.startsWith("mr:")) {
            String button = value.substring(3);
            if (button == "left") {
                mouse.release(MOUSE_LEFT);
                Serial.println("Mouse left release");
            } else if (button == "right") {
                mouse.release(MOUSE_RIGHT);
                Serial.println("Mouse right release");
            } else if (button == "middle") {
                mouse.release(MOUSE_MIDDLE);
                Serial.println("Mouse middle release");
            }
        }
      }
    }
};


void setup() {
  Serial.begin(115200);
  Serial.println("Starting iControl HID device...");

  pinMode(LED_BUILTIN, OUTPUT);

  // Initialize BLE
  BLEDevice::init("iControl HID");
  BLEServer *pServer = BLEDevice::createServer();
  pServer->setCallbacks(new MyServerCallbacks());

  BLEService *pService = pServer->createService(SERVICE_UUID);

  BLECharacteristic *pCharacteristic = pService->createCharacteristic(
                                         CHARACTERISTIC_UUID,
                                         BLECharacteristic::PROPERTY_WRITE
                                       );
  pCharacteristic->setCallbacks(new MyCharacteristicCallbacks());

  pService->start();

  BLEAdvertising *pAdvertising = BLEDevice::getAdvertising();
  pAdvertising->addServiceUUID(SERVICE_UUID);
  pAdvertising->setScanResponse(true);
  pAdvertising->setMinPreferred(0x06);
  pAdvertising->setMinPreferred(0x12);
  BLEDevice::startAdvertising();

  Serial.println("BLE characteristic created. Waiting for a client connection...");

  // Initialize USB HID
  keyboard.begin();
  mouse.begin();
  USB.begin();
}

void loop() {
  unsigned long currentMillis = millis();
  
  if (deviceConnected) {
    // Slow "heartbeat" blink when connected (500ms interval)
    if (currentMillis - lastLedToggle > 500) {
      ledState = !ledState;
      digitalWrite(LED_BUILTIN, ledState);
      lastLedToggle = currentMillis;
    }
  } else {
    // Fast blink when advertising/waiting for connection (250ms interval)
    if (currentMillis - lastLedToggle > 250) {
      ledState = !ledState;
      digitalWrite(LED_BUILTIN, ledState);
      lastLedToggle = currentMillis;
    }
  }
} 