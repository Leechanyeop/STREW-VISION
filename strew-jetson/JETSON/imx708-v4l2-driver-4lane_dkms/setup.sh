#!/usr/bin/bash

DRV_VERSION=0.0.1

DRV_IMX=imx708

if [ ! -e /lib/modules/$(uname -r)/kernel/drivers/media/i2c/imx708.ko.xz.bak ]; then
	sudo mv /lib/modules/$(uname -r)/kernel/drivers/media/i2c/imx708.ko.xz /lib/modules/$(uname -r)/kernel/drivers/media/i2c/imx708.ko.xz.bak
fi

if [ -e /lib/modules/$(uname -r)/kernel/drivers/media/i2c/imx708.ko.xz ]; then
	sudo rm /lib/modules/$(uname -r)/kernel/drivers/media/i2c/imx708.ko.xz
fi

if [ ! -e /boot/overlays/imx708.dtbo.bak ]; then
	echo "/boot/overlays/imx708.dtbo backup."
	sudo cp /boot/overlays/imx708.dtbo /boot/overlays/imx708.dtbo.bak
fi

echo "Uninstalling any previous ${DRV_IMX} module"
#dkms status ${DRV_IMX} | awk -F', ' '{print $2}' | xargs -n1 sudo dkms remove -m ${DRV_IMX} -v 
sudo dkms remove -m ${DRV_IMX} -v ${DRV_VERSION} --all

sudo mkdir -p /usr/src/${DRV_IMX}-${DRV_VERSION}

sudo cp -r $(pwd)/* /usr/src/${DRV_IMX}-${DRV_VERSION}

sudo dkms add -m ${DRV_IMX} -v ${DRV_VERSION}
sudo dkms build -m ${DRV_IMX} -v ${DRV_VERSION}
sudo dkms install -m ${DRV_IMX} -v ${DRV_VERSION}
