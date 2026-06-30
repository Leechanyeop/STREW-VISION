#!/bin/bash

DRV_VERSION=0.0.1

DRV_IMX=imx708

sudo dkms remove -m ${DRV_IMX} -v ${DRV_VERSION} --all

if [ -e /boot/overlays/imx708.dtbo.bak ]; then
	sudo cp /lib/modules$(uname -r)/kernel/drivers/media/i2c/imx708.ko.xz.bak /lib/modules$(uname -r)/kernel/drivers/media/i2c/imx708.ko.xz
else
	echo "/lib/modules$(uname -r)/kernel/drivers/media/i2c/imx708.ko.xz.bak not exists" 
fi

if [ -e /boot/overlays/imx708.dtbo.bak ]; then
	sudo cp /boot/overlays/imx708.dtbo.bak /boot/overlays/imx708.dtbo
else
	echo "imx708.dtbo.bak not exists"
fi

sudo depmod -a