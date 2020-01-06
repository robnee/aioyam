# Rob's Remote

Remote dispatcher for LircPy objects.  send API takes a device name and key
to send. This simulates a button press on a remote.  There is also a config
dictionary that contains 4 keys (each dictionaries themselves.  These dicts
are described below.  The config dict is designed to map directly from a
json representation so it can be kept separate.

### self.config['PROTOCOL']

Defines the handler for each each device.  handler may be LIRC or YAMAHA.

### self.config['MAPPINGS']

If device or key in a send call begins with '@' then then the device and/or key
is first looked up in a self.config['MAPPINGS'] (if available).  This permits
symbolic names to be used in templates to keep them generic.  For example, key
names for things like Volume Up tend to vary (KEY_VOL_UP, KEY_VOLUMEUP etc.)  
Templates can refer to @KEY_VOLUMEUP and be mapped in the config file to the
key name in the Lirc .conf file.  Also, you can create pseudo devices like
@AUDIO to handle audio requests.  Depending on your config these can map to
a TV device or audio receiver.  Again, the template can remain generic.  

send('@AUDIO', '@VOLUP) will first look up the @AUDIO device and the @VOLUP
key in config['MAPPINGS'] and send the resultant command.

### self.config['MACROS']

Defines a series of macros which are just a list of tuples each containing
a device and key.  This is a power on macro in json format:

    "POWER_ON": [
        ["YAMAHA", "KEY_POWERON"],
        ["PANTV", "KEY_POWERON"],
        ["FIOS", "KEY_POWERON"],
        ["PANTV", "KEY_HDMI1"],
        ["YAMAHA", "@INPUT_TV"]
    ]

devices and keys in macros may also be symbolic names using the @ prefix.  To
send this macro call send('@MACRO', 'POWER_ON')

### self.config['CHANNELS']

These are special case macros.  They let you map TV channel names to channel
numbers for ease of dispatch and also to allow you to define the channel number
mappings in one place.  The following macro definition and channel definition
are equivalent:

	"MACROS": {
		"CNN": [
			["CABLE", "KEY_DIGIT_1"],
			["CABLE", "KEY_DIGIT_2"],
			["CABLE", "KEY_DIGIT_3"]
		]
	},

	"CHANNELS": {
		"CNN": ["FIOS", "123"],
	}

The former is sent via send('@MACRO', 'CNN') while the latter is sent via 
send('@CHANNEL', 'CNN').  This depends on the digit keys being defined in your
Lirc .conf file as KEY_DIGIT_n

The is also a @PAUSE command, useful for macros that play too fast.  Example of
a 1/2 second pause:

send('@PAUSE', 0.5)

### Running

nohup run.sh lr.json &

### TODO:


- Document a Lirc setup on Raspberry Pi
- try pelican blog engine
- redefine the channels, macros and devices in json @done
- create a second page with new buttons
- standardize on key names
- add display:block to a tag to respect width
