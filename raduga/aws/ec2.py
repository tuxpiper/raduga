from time import sleep

class AWSEC2(object):
    def __init__(self, target):
        self.conn = target.get_ec2_conn()

    def stop_instance(self, instance_id):
        print "Stopping %s ..." % instance_id
        self.conn.stop_instances(instance_id)

        # Wait until instance is indeed stopped
        print "Waiting until %s is stopped ..." % instance_id
        instance = self.conn.get_only_instances(instance_id)[0]
        while instance.state != 'stopped':
            instance = self.conn.get_only_instances(instance_id)[0]
            sleep(15)

    def create_ami(self, instance_id, name, description, tags):
        print "Creating image from %s ..." % instance_id
        instance = self.conn.get_only_instances(instance_id)[0]
        if instance.state != 'stopped':
            raise RuntimeError("Won't create AMI from non-stopped instance")
        image_id = self.conn.create_image(instance_id, name, description)
        # Add tags to the image
        print "Adding tags to AMI %s ..." % image_id
        self.conn.create_tags(image_id, tags)

        # Wait until the image is available
        print "Waiting until AMI %s is available ..." % image_id
        ami = self.conn.get_all_images(image_id)[0]
        while ami.state != 'available':
            ami = self.conn.get_all_images(image_id)[0]
            print "AMI is %s ..." + ami.state
            sleep(15)

    def find_ami(self, **tags):
        filters = dict(map(lambda (k,v): ("tag:"+k,v), tags.items()))
        results = self.conn.get_all_images(owners=['self'], filters=filters)
        if len(results) == 0:
            return None
        elif len(results) == 1:
            return results[0].id
        else:
            raise RuntimeError("More than ona AMI is matching the requested tags (??!)")
